const dom = {
  status: document.getElementById("listViewStatus"),
  search: document.getElementById("listSearch"),
  linesContainer: document.getElementById("linesContainer"),

  floatingBar: document.getElementById("floatingBar"),
  floatingCount: document.getElementById("floatingCount"),
  floatingClearBtn: document.getElementById("floatingClearBtn"),
  floatingApplyBtn: document.getElementById("floatingApplyBtn"),
};

let fullData = [];
let lineStatusMap = new Map();

// UI State
let searchQuery = "";
let expandedLines = new Set();
let selectedSegments = new Set();

const SVGS = {
  checkSquare: `<svg class="w-6 h-6 text-[#0063D3]" stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24"><polyline points="9 11 12 14 22 4"></polyline><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg>`,
  square: `<svg class="w-6 h-6" stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>`,
  partial: `<div class="w-6 h-6 rounded bg-[#0063D3] flex items-center justify-center"><div class="w-3 h-0.5 bg-white rounded-full"></div></div>`,
  chevronUp: `<svg class="w-5 h-5" stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24"><polyline points="18 15 12 9 6 15"></polyline></svg>`,
  chevronDown: `<svg class="w-5 h-5" stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"></polyline></svg>`,
  commit: `<svg class="w-4 h-4" stroke="currentColor" fill="none" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"></circle><line x1="3" y1="12" x2="9" y2="12"></line><line x1="15" y1="12" x2="21" y2="12"></line></svg>`
};

function esc(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));
}

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} error`);
  return res.json();
}

function groupData(features) {
  const lines = new Map();
  for (const line of (features.lines || [])) {
    lines.set(line.line_id, {
      line_id: line.line_id,
      line_name: line.name || line.line_id,
      segments: []
    });
  }
  for (const seg of (features.segments || [])) {
    const group = lines.get(seg.line_id) || {
      line_id: seg.line_id,
      line_name: seg.line_id,
      segments: []
    };
    group.segments.push({
      segment_id: seg.id,
      segment_name: seg.name || seg.id,
      point_count: Array.isArray(seg.geometry) ? seg.geometry.length : 0
    });
    lines.set(seg.line_id, group);
  }
  return Array.from(lines.values()).sort((a, b) => a.line_name.localeCompare(b.line_name));
}

async function loadStatuses(lines) {
  const pairs = await Promise.all(
    lines.map(async (line) => {
      try {
        const payload = await getJSON(`/api/line_status?line_id=${encodeURIComponent(line.line_id)}`);
        return [line.line_id, payload];
      } catch {
        return [line.line_id, null];
      }
    })
  );
  lineStatusMap = new Map(pairs);
}

// Rendering Main UI
function render() {
  const q = searchQuery.toLowerCase();
  const html = [];

  for (const line of fullData) {
    const lineMatches = line.line_name.toLowerCase().includes(q) || line.line_id.toLowerCase().includes(q);
    const matchedSegments = line.segments.filter(seg => 
      seg.segment_id.toLowerCase().includes(q) || seg.segment_name.toLowerCase().includes(q)
    );

    if (!lineMatches && !matchedSegments.length && q !== "") continue;
    
    // Determine selections
    const segmentIds = line.segments.map(s => s.segment_id);
    const allSelected = segmentIds.length > 0 && segmentIds.every(id => selectedSegments.has(id));
    const someSelected = segmentIds.some(id => selectedSegments.has(id)) && !allSelected;
    
    const isExpanded = expandedLines.has(line.line_id) || (q !== "" && matchedSegments.length > 0);
    
    const statusObj = lineStatusMap.get(line.line_id);
    let statusText = "Not applied";
    let statusClasses = "bg-gray-100 text-gray-600 border-gray-200";
    if (statusObj?.applied) {
      statusText = "Active Permit";
      statusClasses = "bg-green-100 text-green-700 border-green-200";
    }

    const segmentsToRender = q !== "" && !lineMatches ? matchedSegments : line.segments;

    html.push(`
      <div class="bg-white border rounded-xl shadow-sm overflow-hidden transition-all ${someSelected || allSelected ? 'border-[#0063D3]' : 'border-gray-200'}">
        <div class="w-full flex flex-col sm:flex-row sm:items-center justify-between p-5 bg-white hover:bg-gray-50 transition-colors cursor-pointer" data-action="toggle-line" data-line="${esc(line.line_id)}">
          
          <div class="flex items-center gap-4">
            <button class="text-gray-400 hover:text-[#0063D3] transition-colors p-1 border-0 bg-transparent cursor-pointer" data-action="select-line" data-line="${esc(line.line_id)}">
              ${allSelected ? SVGS.checkSquare : someSelected ? SVGS.partial : SVGS.square}
            </button>

            <div class="w-12 h-12 rounded-lg bg-[#0063D3]/10 text-[#0063D3] flex items-center justify-center font-black text-xl border border-[#0063D3]/20">
              ${esc(line.line_id)}
            </div>
            <div>
              <h3 class="font-bold text-lg text-gray-900 flex items-center gap-2 m-0 border-0">
                ${esc(line.line_name)} <span class="text-gray-400 font-normal">(${esc(line.line_id)})</span>
              </h3>
              <div class="text-sm text-gray-500 font-medium mt-0.5">
                ${line.segments.length} segment(s)
              </div>
            </div>
          </div>
          
          <div class="flex items-center gap-4 mt-4 sm:mt-0 ml-12 sm:ml-0">
            <span class="px-3 py-1 rounded-full text-xs font-bold border ${statusClasses}">
              ${esc(statusText)}
            </span>
            <div class="text-gray-400">
              ${isExpanded ? SVGS.chevronUp : SVGS.chevronDown}
            </div>
          </div>
        </div>

        ${isExpanded ? `
          <div class="border-t border-gray-100 bg-gray-50/50 p-2">
            <div class="grid gap-2">
              ${segmentsToRender.map(seg => {
                const isSelected = selectedSegments.has(seg.segment_id);
                return `
                  <div class="flex flex-col sm:flex-row sm:items-center justify-between p-4 bg-white border rounded-lg transition-all cursor-pointer ${isSelected ? 'border-[#0063D3] shadow-sm ring-1 ring-[#0063D3]' : 'border-gray-200 hover:border-[#0063D3]/50'}" data-action="select-segment" data-segment="${esc(seg.segment_id)}">
                    <div class="flex items-center gap-4 mb-2 sm:mb-0">
                      <div class="${isSelected ? 'text-[#0063D3]' : 'text-gray-300'}">
                        ${isSelected ? SVGS.checkSquare : SVGS.square}
                      </div>
                      <div class="p-2 rounded-md transition-colors ${isSelected ? 'bg-[#0063D3]/10 text-[#0063D3]' : 'bg-gray-100 text-gray-500'}">
                        ${SVGS.commit}
                      </div>
                      <span class="font-bold text-gray-900 text-base">${esc(seg.segment_name)}</span>
                    </div>
                    
                    <div class="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm ml-9 sm:ml-0">
                      <div class="flex items-center gap-1.5">
                        <span class="text-gray-400 font-medium">ID:</span>
                        <span class="font-mono text-gray-700 bg-gray-100 px-2 py-0.5 rounded text-xs border border-gray-200">
                          ${esc(seg.segment_id)}
                        </span>
                      </div>
                      <div class="flex items-center gap-1.5">
                        <span class="text-gray-400 font-medium">Points:</span>
                        <span class="font-mono text-gray-700 bg-gray-100 px-2 py-0.5 rounded text-xs border border-gray-200">
                          ${esc(seg.point_count)}
                        </span>
                      </div>
                    </div>
                  </div>
                `;
              }).join("")}
            </div>
          </div>
        ` : ""}
      </div>
    `);
  }

  dom.linesContainer.innerHTML = html.length ? html.join("") : `<div class="p-8 text-center text-gray-500 font-medium">No results found for "${esc(q)}"</div>`;
}

function updateFloatingBar() {
  const count = selectedSegments.size;
  if (count > 0) {
    dom.floatingCount.textContent = count;
    dom.floatingBar.style.visibility = "visible";
    dom.floatingBar.classList.remove("translate-y-full");
    dom.floatingBar.classList.add("translate-y-0");
  } else {
    dom.floatingBar.classList.remove("translate-y-0");
    dom.floatingBar.classList.add("translate-y-full");
    setTimeout(() => {
      if (selectedSegments.size === 0) dom.floatingBar.style.visibility = "hidden";
    }, 300);
  }
}

// Events delegation
dom.linesContainer.addEventListener("click", e => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.getAttribute("data-action");
  
  if (action === "toggle-line") {
    const lineId = btn.getAttribute("data-line");
    if (expandedLines.has(lineId)) expandedLines.delete(lineId);
    else expandedLines.add(lineId);
    render();
  }
  
  if (action === "select-line") {
    e.stopPropagation();
    const lineId = btn.getAttribute("data-line");
    const line = fullData.find(l => l.line_id === lineId);
    if (!line) return;
    
    const segmentIds = line.segments.map(s => s.segment_id);
    const allSelected = segmentIds.every(id => selectedSegments.has(id));
    
    if (allSelected) {
        segmentIds.forEach(id => selectedSegments.delete(id));
    } else {
        segmentIds.forEach(id => selectedSegments.add(id));
    }
    render();
    updateFloatingBar();
  }
  
  if (action === "select-segment") {
    e.stopPropagation();
    const segId = btn.getAttribute("data-segment");
    if (selectedSegments.has(segId)) selectedSegments.delete(segId);
    else selectedSegments.add(segId);
    render();
    updateFloatingBar();
  }
});

dom.search.addEventListener("input", e => {
  searchQuery = e.target.value;
  render();
});

dom.floatingClearBtn.addEventListener("click", () => {
  selectedSegments.clear();
  render();
  updateFloatingBar();
});

dom.floatingApplyBtn.addEventListener("click", () => {
  if (selectedSegments.size === 0) return;
  const arrayIds = Array.from(selectedSegments).map(encodeURIComponent);
  window.location.href = "/?apply_segments=" + arrayIds.join(",") + "#mapPage";
});

// Boot Sequence
async function init() {
  try {
    dom.status.textContent = "Loading network data...";
    const features = await getJSON("/api/features");
    fullData = groupData(features);
    
    // Sort and initialize top 2 open
    expandedLines.add(fullData[0]?.line_id);
    expandedLines.add(fullData[1]?.line_id);

    render();
    
    // Load status silently
    dom.status.textContent = "Loading statuses...";
    await loadStatuses(fullData);
    render();
    
    dom.status.textContent = "Data Up to Date";
    setTimeout(() => { dom.status.style.display = 'none'; }, 2000);
  } catch (err) {
    console.error(err);
    if(dom.status) {
        dom.status.textContent = `Error: ${err.message}`;
        dom.status.classList.add("text-red-600");
    }
  }
}

init();
