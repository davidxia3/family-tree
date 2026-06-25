"""Generate a STANDALONE HTML editor (no server) for semi-manual grid positioning.

Model: everything on the canvas is an ENTITY (a tile, or a horizontal/vertical line segment).
An entity is FREE iff it has no anchor; only free entities are blue and can be dragged (dragging
moves it plus everything anchored to it, transitively). Anchored entities move only with their
anchor. Tiles start FREE.

Geometry: tile X is now ARBITRARY (no vertical grid lines, no column snap) so a parent can sit
exactly between any two children. Tile Y still snaps to the tall generation rows. Line-segment Y
snaps to the horizontal grid lines; segment X is free (the auto-tools place them at tile centres).

Interactions (black & white, for debugging):
  * LEFT-drag a BLUE (free) entity -> moves it + its dependents (Y snaps to rows, X is free).
  * LEFT-click an entity -> toggle it in the yellow SELECTION (drives the tools + line deletion).
  * with exactly one entity selected, the bottom-right panel shows its coordinates (tile: x + row;
    line: endpoint px) — editable if FREE, read-only (disabled) if anchored. Anchored LINES also
    lose their drag handles, so their endpoints can't be picked up.
  * RIGHT-click an entity -> ANCHORING mode: it glows blue; left-click / box-drag FREE entities to
    attach them (green); click green to detach. Already-anchored entities and the target's ancestors
    dim out and are not selectable (locked / would cycle). Right-click again (or Esc) to finish.
  * Pack subtrees: select 2+ ROOT tiles in the SAME row; packs them to the minimum distance (per
    HALF-row contour) and chains anchors Tn→…→T2→T1 — the LEFTMOST tile T1 stays the lone root.
    Built from the right pair (T(n-1),Tn) leftward; a single pair is just the n=2 case.
  * Busbar: select 1 parent + its children (one row below); centres the parent over them, draws the
    busbar + drops, and anchors those new lines AND every still-free child to the parent (children
    that already have an anchor keep it). A single child -> one full-gap vertical, no bar.
  * Marriage: select 2 same-row tiles; draws a horizontal line between their facing edges (free).
    Pack chains anchors and Busbar anchors its lines+free children; Marriage just draws.
  * +H / +V spawn segments; drag endpoints to resize. Delete / the Delete button removes selected
    LINES (never tiles). Save -> downloads positions.yaml.
"""
from __future__ import annotations

import json
from typing import List

from .layout import LayoutResult


def build_editor_html(ds, cfg: dict, lay: LayoutResult) -> str:
    L = cfg["layout"]
    char_box = L["char_box"]
    pad = L["tile_pad"]
    tile_w = char_box + 2 * pad
    margin = L["margin"]
    any_tile = next(iter(lay.tiles.values()))
    tile_h = any_tile.height
    v_gap = L["v_gap"]

    tiles: List[dict] = []
    for t in lay.tiles.values():
        tiles.append({"id": t.id, "name": t.name,
                      "col": round((t.x - margin) / tile_w), "row": t.gen})

    data = {"tiles": tiles, "cellW": tile_w, "cellH": tile_h, "gap": v_gap,
            "charBox": char_box, "pad": pad}
    return _HTML.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))


_HTML = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>family-tree editor</title>
<style>
  *{box-sizing:border-box;} html,body{margin:0;height:100%;}
  body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#000;color:#eee;overflow:hidden;}
  #bar{position:fixed;top:0;left:0;right:0;height:42px;background:#111;border-bottom:1px solid #333;
       display:flex;align-items:center;gap:8px;padding:0 12px;z-index:10;font-size:13px;}
  #bar button{background:#222;color:#ddd;border:1px solid #444;border-radius:4px;padding:5px 10px;cursor:pointer;}
  #bar button:hover{background:#333;} #bar .sp{flex:1;} #bar .div{width:1px;height:22px;background:#333;}
  #mode{position:fixed;left:10px;bottom:10px;z-index:10;background:rgba(20,20,20,.92);border:1px solid #444;
        border-radius:6px;padding:8px 12px;font-size:13px;max-width:60vw;line-height:1.45;}
  #mode b{color:#5aa0ff;} #mode .msg{color:#ffd23a;}
  #coord{position:fixed;right:10px;bottom:10px;z-index:10;background:rgba(20,20,20,.95);border:1px solid #444;
         border-radius:6px;padding:8px 12px;font-size:13px;display:none;}
  #coord b{color:#5aa0ff;} #coord .t{color:#888;font-size:11px;}
  #coord label{display:inline-block;margin:5px 8px 0 0;color:#bbb;}
  #coord input{width:74px;background:#111;color:#eee;border:1px solid #555;border-radius:3px;padding:3px 5px;margin-left:5px;font-family:inherit;}
  #coord input:disabled{color:#999;background:#0a0a0a;border-color:#333;cursor:not-allowed;}
  #coord .lock{color:#c98a3a;}
  #wrap{position:absolute;top:42px;left:0;right:0;bottom:0;overflow:auto;background:#000;}
  svg{display:block;}
  .solid{stroke:#fff;stroke-width:1;opacity:.4;fill:none;}
  .dash{stroke:#fff;stroke-width:.7;opacity:.2;stroke-dasharray:4 5;}
  .ent{cursor:grab;}
  .trect{fill:#fff;stroke:#000;stroke-width:1.5;}
  .ttext{fill:#000;font-family:"Songti SC",STSong,serif;}
  .seg{stroke:#fff;stroke-width:2.5;}
  .hit{stroke:#000;stroke-opacity:0;stroke-width:16;fill:none;}
  .handle{fill:#000;stroke:#fff;stroke-width:1.5;cursor:crosshair;}
</style></head>
<body>
<div id="bar">
  <button id="addH">+ H line</button><button id="addV">+ V line</button>
  <span class="div"></span>
  <button id="pack">Pack subtrees</button><button id="bus">Busbar</button><button id="mar">Marriage</button>
  <span class="div"></span>
  <button id="del">Delete line</button>
  <span class="sp"></span>
  <button id="zo">−</button><button id="zi">+</button>
  <button id="save">Save positions.yaml</button>
</div>
<div id="wrap"><svg id="cv" xmlns="http://www.w3.org/2000/svg"></svg></div>
<div id="mode"></div>
<div id="coord"></div>
<script>
const D=/*__DATA__*/;
const CW=D.cellW, CH=D.cellH, GAP=D.gap, PITCH=CH+GAP, CB=D.charBox, PAD=D.pad;
const GFRACS=[1/2,3/4,7/8];                                  // gap horizontals: 1/2, 1/4, 1/8 from the BOTTOM
const cv=document.getElementById('cv'), modeEl=document.getElementById('mode'), wrap=document.getElementById('wrap'), coordEl=document.getElementById('coord');

const ents={};
for(const t of D.tiles) ents[t.id]={id:t.id,type:'tile',anchor:null,name:t.name,x:t.col*CW,y:t.row*PITCH};
let segN=0, scale=0.4, target=null, selSet=new Set(), elMap={}, boxEl=null, msg='';  // target = the anchor we attach TO

const deps=id=>Object.values(ents).filter(e=>e.anchor===id).map(e=>e.id);
function subtree(id){ const out=[],st=[id]; while(st.length){ const n=st.pop();
  for(const c of deps(n)) if(!out.includes(c)){ out.push(c); st.push(c);} } return out; }
function ancestors(id){ const out=[]; let a=ents[id].anchor; while(a&&!out.includes(a)){ out.push(a); a=ents[a].anchor; } return out; }
function center(e){ return e.type==='tile'?[e.x+CW/2,e.y+CH/2]:e.type==='hseg'?[(e.x1+e.x2)/2,e.y]:[e.x,(e.y1+e.y2)/2]; }
const isFree=id=>ents[id].anchor===null;                    // ONLY free => blue / movable
function moveEnt(e,dx,dy){ if(e.type==='tile'){e.x+=dx;e.y+=dy;}
  else if(e.type==='hseg'){e.y+=dy;e.x1+=dx;e.x2+=dx;} else {e.x+=dx;e.y1+=dy;e.y2+=dy;} }
function moveSubtree(id,dx,dy){ for(const m of [id,...subtree(id)]) moveEnt(ents[m],dx,dy); }
function bbox(e){ return e.type==='tile'?[e.x,e.y,CW,CH]
  : e.type==='hseg'?[Math.min(e.x1,e.x2),e.y-3,Math.abs(e.x2-e.x1),6]
  : [e.x-3,Math.min(e.y1,e.y2),6,Math.abs(e.y2-e.y1)]; }
function rightEdge(e){ return e.type==='tile'?e.x+CW : e.type==='hseg'?Math.max(e.x1,e.x2) : e.x; }
function leftEdge(e){ return e.type==='tile'?e.x : e.type==='hseg'?Math.min(e.x1,e.x2) : e.x; }
const rowOf=e=>Math.round(e.y/PITCH);
function ySpan(e){ return e.type==='tile'?[e.y,e.y+CH] : e.type==='hseg'?[e.y,e.y] : [Math.min(e.y1,e.y2),Math.max(e.y1,e.y2)]; }
function subBands(e){                                        // HALF-row bands: 2r = tile of row r, 2r+1 = the gap below it
  const [yt,yb]=ySpan(e), o=[];                              // (so a busbar in the gap can't block a TILE in the row above it)
  for(let r=Math.max(0,Math.floor(yt/PITCH)-1); r<=Math.floor(yb/PITCH)+1; r++){
    const tT=r*PITCH, tB=tT+CH, gB=(r+1)*PITCH;
    if(yt<tB && yb>tT) o.push(2*r);                          // overlaps the tile band [tT,tB]
    if(yt<gB && yb>tB) o.push(2*r+1); }                      // overlaps the gap band [tB,gB]
  return o; }

// snapping. tiles: X free, Y -> rows. segments: Y -> horizontal grid lines, X free.
const snapCell=(v,p)=>Math.round(v/p)*p;
const HYoff=[0, CH/2, CH, CH+GAP/2, CH+3*GAP/4, CH+7*GAP/8];  // tile top, tile centre, tile bottom, + 3 gap lines
function snapHY(y){ let best=y,bd=1e9,r=Math.floor(y/PITCH);
  for(let k=r-1;k<=r+1;k++) for(const o of HYoff){ const t=k*PITCH+o; if(Math.abs(t-y)<bd){bd=Math.abs(t-y);best=t;} } return best; }
function moveDelta(d,rdx,rdy){ const s=d.start[d.id], e0=ents[d.id];
  if(e0.type==='tile') return [rdx, snapCell(rdy,PITCH)];                 // X free, Y -> row
  if(e0.type==='hseg') return [rdx, snapHY(s.y+rdy)-s.y];
  return [rdx, snapHY(s.y1+rdy)-s.y1]; }
function dims(){ let W=CW,H=PITCH; for(const e of Object.values(ents)){ const[x,y,w,h]=bbox(e); W=Math.max(W,x+w); H=Math.max(H,y+h);} return [W+3*CW,H+2*PITCH]; }

let DIS=new Set();                                          // entities that would create a cycle (target's ancestors)
function hlColor(id){
  if(target){ if(id===target) return '#3a86ff';             // the anchor we attach to
              if(ents[id].anchor===target) return '#19d219'; // already attached (green)
              return null; }
  if(selSet.has(id)) return '#ffd23a';                       // in the selection (yellow)
  return isFree(id)?'#3a86ff':null;                          // free => blue / movable
}
function entSvg(e){
  const col=hlColor(e.id); const HW=6/scale; let s=`<g class="ent" data-id="${e.id}"${DIS.has(e.id)?' opacity="0.28"':''}>`;
  if(col){ const[bx,by,bw,bh]=bbox(e);
    s+=`<rect x="${bx-HW}" y="${by-HW}" width="${bw+2*HW}" height="${bh+2*HW}" fill="none" stroke="${col}" stroke-width="${HW}" rx="${HW}"/>`; }
  if(e.type==='tile'){ const cx=e.x+CW/2; let txt='';
    [...e.name].forEach((ch,i)=>{ txt+=`<tspan x="${cx}" y="${e.y+PAD+CB*(i+0.78)}">${ch}</tspan>`; });
    s+=`<rect class="trect" x="${e.x}" y="${e.y}" width="${CW}" height="${CH}" rx="3"/><text class="ttext" text-anchor="middle" font-size="30">${txt}</text>`;
  } else { const H=e.type==='hseg', x1=H?e.x1:e.x, y1=H?e.y:e.y1, x2=H?e.x2:e.x, y2=H?e.y:e.y2;
    s+=`<line class="seg" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/><line class="hit" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
    if(e.anchor===null) s+=`<rect class="handle" data-end="1" x="${x1-7}" y="${y1-7}" width="14" height="14"/><rect class="handle" data-end="2" x="${x2-7}" y="${y2-7}" width="14" height="14"/>`; }  // endpoints draggable only when FREE
  return s+'</g>';
}
function render(){
  DIS = new Set();                                          // greyed + NON-selectable while ANCHORING:
  if(target){ const anc=new Set(ancestors(target));          //   already anchored elsewhere, or an ancestor (would cycle)
    for(const id in ents){ const a=ents[id].anchor;
      if(id!==target && ((a!==null && a!==target) || anc.has(id))) DIS.add(id); } }
  const [W,H]=dims(); cv.setAttribute('width',W*scale); cv.setAttribute('height',H*scale); cv.setAttribute('viewBox',`0 0 ${W} ${H}`);
  let grid=''; const nrows=Math.ceil(H/PITCH)+1;            // horizontal grid only (tiles have arbitrary X)
  for(let r=0;r<nrows;r++){ const y0=r*PITCH;
    grid+=`<line class="solid" x1="0" y1="${y0}" x2="${W}" y2="${y0}"/>`            // tile top
        +`<line class="solid" x1="0" y1="${y0+CH}" x2="${W}" y2="${y0+CH}"/>`       // tile bottom
        +`<line class="dash" x1="0" y1="${y0+CH/2}" x2="${W}" y2="${y0+CH/2}"/>`;   // tile centre
    for(const f of GFRACS) grid+=`<line class="dash" x1="0" y1="${y0+CH+GAP*f}" x2="${W}" y2="${y0+CH+GAP*f}"/>`; }
  let e=''; for(const k in ents) e+=entSvg(ents[k]);
  cv.innerHTML = `<rect x="0" y="0" width="${W}" height="${H}" fill="#000"/>`
    + `<g id="grid">${grid}</g>` + `<g id="ents">${e}</g>`
    + `<rect id="boxsel" fill="#3a86ff" fill-opacity="0.12" stroke="#3a86ff" stroke-dasharray="6 4" visibility="hidden"/>`;
  elMap={}; for(const g of cv.querySelectorAll('.ent')) elMap[g.dataset.id]=g; boxEl=cv.querySelector('#boxsel');
  updateMode();
}
function updateMode(){
  const m = msg?`<br><span class="msg">${msg}</span>`:'';
  if(target){
    modeEl.innerHTML = `<b>ANCHORING → ${target}</b> (blue) · left-click or box-drag entities to attach (green) · click green to detach`
      + `<br>dimmed = already anchored, or its ancestors (would cycle) · <b>Esc</b> or right-click <b>${target}</b> to finish` + m;
  } else modeEl.innerHTML = `<b>EDIT</b> · left-click = select (yellow) · drag blue = move (X free, Y snaps) · <b>right-click</b> = ANCHOR`
    + `<br><b>Pack</b>: 2+ same-row roots · <b>Busbar</b>: parent + children · <b>Marriage</b>: 2 same-row tiles · +H/+V lines · Delete removes selected lines`
    + (selSet.size===1?` · <b style="color:#ffd23a">1 selected — edit coords ↘</b>`:selSet.size?` · <b style="color:#ffd23a">${selSet.size} selected</b>`:'') + m;
  updateCoordPanel();
}
// ---- manual coordinate entry (only for a single, FREE entity; anchored ones follow their anchor) ----
function updateCoordPanel(){
  const ids=[...selSet], e=(!target && ids.length===1)?ents[ids[0]]:null;
  if(!e){ coordEl.style.display='none'; return; }
  coordEl.style.display='block';
  const locked = e.anchor!==null;                            // anchored: still SHOW coords, just read-only
  const f=(lbl,k,v)=>`<label>${lbl}<input data-k="${k}" type="number" step="1" value="${Math.round(v)}"${locked?' disabled':''}></label>`;
  const fields = e.type==='tile' ? f('x','x',e.x)+f('row','row',e.y/PITCH)
               : e.type==='hseg' ? f('y','y',e.y)+f('x1','x1',e.x1)+f('x2','x2',e.x2)
               :                   f('x','x',e.x)+f('y1','y1',e.y1)+f('y2','y2',e.y2);
  coordEl.innerHTML=`<b>${e.id}</b> <span class="t">${e.type}</span>`
    + (locked?` <span class="lock">⚓ ${e.anchor} (read-only)</span>`:'') + `<br>${fields}`;
  if(!locked) for(const inp of coordEl.querySelectorAll('input'))
    inp.addEventListener('change',ev=>applyCoord(e.id, ev.target.dataset.k, ev.target.value));
}
function applyCoord(id,key,raw){
  const e=ents[id]; if(!e || e.anchor!==null) return;        // never edit an anchored entity
  const v=parseFloat(raw); if(isNaN(v)) return;
  if(e.type==='tile'){ const nx=key==='x'?v:e.x, ny=key==='row'?Math.round(v)*PITCH:e.y;
    moveSubtree(id, nx-e.x, ny-e.y); }                       // a tile MOVES (carries its subtree, like a drag)
  else e[key]=v;                                             // a line endpoint is set directly (reshape)
  render();
}
render();

// ---- interaction ----
let drag=null;
const userXY=e=>{ const r=cv.getBoundingClientRect(); return [(e.clientX-r.left)/scale,(e.clientY-r.top)/scale]; };
cv.addEventListener('mousedown',e=>{
  if(e.button!==0) return;                                   // ONLY left button drags / picks up / clicks; right button → contextmenu
  msg='';
  const entEl=e.target.closest('.ent'); const id=entEl?entEl.dataset.id:null;
  if(target){ const[ux,uy]=userXY(e); drag={kind:'box',id,sx:e.clientX,sy:e.clientY,ux,uy}; e.preventDefault(); return; }  // ANCHORING: drag = box-select
  if(!id){ if(selSet.size){selSet.clear();} render(); return; }   // empty click: clear selection
  const handle=e.target.closest('.handle');
  if(handle && isFree(id)){ drag={kind:'resize',id,end:handle.dataset.end,sx:e.clientX,sy:e.clientY,start:{...ents[id]}}; e.preventDefault(); return; }  // anchored line endpoints can't be dragged
  if(isFree(id)){ const ids=[id,...subtree(id)]; const start={}; for(const m of ids)start[m]={...ents[m]};
    drag={kind:'move',id,ids,sx:e.clientX,sy:e.clientY,start}; }
  else drag={kind:'noop',id,sx:e.clientX,sy:e.clientY};
  e.preventDefault();
});
window.addEventListener('mousemove',e=>{
  if(!drag)return;
  if(drag.kind==='box'){ const[ux,uy]=userXY(e);
    boxEl.setAttribute('x',Math.min(ux,drag.ux)); boxEl.setAttribute('y',Math.min(uy,drag.uy));
    boxEl.setAttribute('width',Math.abs(ux-drag.ux)); boxEl.setAttribute('height',Math.abs(uy-drag.uy));
    boxEl.setAttribute('stroke-width',2/scale); boxEl.setAttribute('visibility','visible'); return; }
  if(drag.kind==='noop')return;
  const rdx=(e.clientX-drag.sx)/scale, rdy=(e.clientY-drag.sy)/scale;
  if(drag.kind==='move'){ const [dx,dy]=moveDelta(drag,rdx,rdy);
    for(const m of drag.ids){ const g=elMap[m]; if(g) g.setAttribute('transform',`translate(${dx} ${dy})`); }
  } else { const o=ents[drag.id], s=drag.start, g=elMap[drag.id];
    if(o.type==='hseg'){ if(drag.end==='1')o.x1=s.x1+rdx; else o.x2=s.x2+rdx;     // hseg endpoint: X free
      g.querySelectorAll('.seg,.hit').forEach(l=>{l.setAttribute('x1',o.x1);l.setAttribute('x2',o.x2);});
      const h=g.querySelectorAll('.handle'); h[0].setAttribute('x',o.x1-7); h[1].setAttribute('x',o.x2-7);
    } else { if(drag.end==='1')o.y1=snapHY(s.y1+rdy); else o.y2=snapHY(s.y2+rdy);  // vseg endpoint: Y -> grid line
      g.querySelectorAll('.seg,.hit').forEach(l=>{l.setAttribute('y1',o.y1);l.setAttribute('y2',o.y2);});
      const h=g.querySelectorAll('.handle'); h[0].setAttribute('y',o.y1-7); h[1].setAttribute('y',o.y2-7); }
  }
});
window.addEventListener('mouseup',e=>{
  if(!drag)return;
  const moved = drag.kind!=='noop' && (Math.abs(e.clientX-drag.sx)>4||Math.abs(e.clientY-drag.sy)>4);
  if(drag.kind==='box'){
    if(moved){ const[ux,uy]=userXY(e); const xl=Math.min(ux,drag.ux),xh=Math.max(ux,drag.ux),yl=Math.min(uy,drag.uy),yh=Math.max(uy,drag.uy);
      for(const id in ents){ if(id===target||DIS.has(id))continue; const[cx,cy]=center(ents[id]);
        if(cx>=xl&&cx<=xh&&cy>=yl&&cy<=yh) ents[id].anchor=target; } }
    else anchorClick(drag.id);
    render();
  }
  else if(drag.kind==='move' && moved){ const [dx,dy]=moveDelta(drag,(e.clientX-drag.sx)/scale,(e.clientY-drag.sy)/scale);
    for(const m of drag.ids) moveEnt(ents[m],dx,dy); render(); }
  else if(drag.kind==='resize' && moved){ render(); }
  else if(!moved){ editClick(drag.id); }
  drag=null;
});
cv.addEventListener('contextmenu',e=>{                       // RIGHT-click drives ANCHORING (no browser menu)
  e.preventDefault();
  const entEl=e.target.closest('.ent'); const id=entEl?entEl.dataset.id:null; msg='';
  if(target){ target=(!id||id===target)?null:id; render(); return; }   // in ANCHORING: switch anchor, or (self/empty) finish
  if(id){ target=id; selSet.clear(); }                       // in EDIT: make THIS the anchor → ANCHORING mode
  render();
});
function editClick(id){                                      // a LEFT-click while in EDIT mode: toggle the yellow selection
  if(selSet.has(id)) selSet.delete(id); else selSet.add(id); // (tiles AND lines)
  render();
}
function anchorClick(id){                                    // a LEFT-click while ANCHORING (onto `target`)
  if(!id || id===target || DIS.has(id)) return;              // self / locked / would-cycle: ignore
  ents[id].anchor = (ents[id].anchor===target) ? null : target;    // attach (green) ⇄ detach
  render();
}
function delLines(){                                         // delete selected SEGMENTS only — never tiles
  let n=0; for(const id of [...selSet]){ const e=ents[id]; if(!e||e.type==='tile') continue;
    for(const k in ents) if(ents[k].anchor===id) ents[k].anchor=null;              // orphans become free
    delete ents[id]; selSet.delete(id); n++; }
  if(target&&!ents[target]) target=null;
  msg = n?`Deleted ${n} line(s).`:'No lines in the selection to delete.'; render();
}
window.addEventListener('keydown',e=>{
  if(e.key==='Escape'){ target=null; selSet.clear(); msg=''; render(); }
  else if((e.key==='Delete'||e.key==='Backspace')&&selSet.size){ e.preventDefault(); delLines(); }
});

// ---- Pack subtrees: place two selected root subtrees side by side at the minimum distance ----
function packSubtrees(){                                     // pack 2+ same-row roots left→right, chaining anchors T1→T2→…→Tn
  const roots=[...selSet].filter(id=>ents[id]&&ents[id].type==='tile'&&ents[id].anchor===null);
  if(roots.length<2){ msg='Pack needs 2+ ROOT tiles selected (no anchor).'; render(); return; }
  const r0=rowOf(ents[roots[0]]);
  if(!roots.every(id=>rowOf(ents[id])===r0)){ msg='Pack: all selected tiles must be in the same row.'; render(); return; }
  const T=roots.sort((a,b)=>center(ents[a])[0]-center(ents[b])[0]);     // T[0] leftmost … T[n-1] rightmost
  for(let i=T.length-2;i>=0;i--){ packPair(T[i],T[i+1]); ents[T[i+1]].anchor=T[i]; }  // from the RIGHT pair leftward; chain Tn→…→T1
  selSet.clear(); msg=`Packed ${T.length} subtrees into a chain rooted at ${T[0]}.`; render();
}
function packPair(L,R){                                      // place R's subtree one tile-gap right of L's GROUP (per HALF-row contour)
  const ext=(root,side)=>{ const cx=center(ents[root])[0], rb=2*rowOf(ents[root]), o={};   // contour is re-derived over the FULL subtree
    for(const id of [root,...subtree(root)]){ const e=ents[id]; const v=side>0?rightEdge(e)-cx:cx-leftEdge(e);
      for(const b of subBands(e)){ const i=b-rb; o[i]=Math.max(o[i]??-Infinity,v); } } return o; };
  const Le=ext(L,1), Re=ext(R,-1);                           // L's rightward reach / R's leftward reach
  let M=-Infinity; for(const i in Le) if(i in Re) M=Math.max(M,Le[i]+Re[i]);   // tightest shared half-row
  if(M===-Infinity) M=0;                                     // no shared band → one tile-width apart
  const tr=Math.min(rowOf(ents[L]),rowOf(ents[R]));          // (same-row in practice; raise the lower root defensively)
  moveSubtree(L,0,(tr-rowOf(ents[L]))*PITCH);
  moveSubtree(R,(center(ents[L])[0]+M+CW)-center(ents[R])[0],(tr-rowOf(ents[R]))*PITCH);   // centres exactly M+W apart
}

// ---- Busbar: centre a parent over its children and draw the n+2 lineage lines ----
function drawBusbar(){
  const tiles=[...selSet].filter(id=>ents[id]&&ents[id].type==='tile');
  if(tiles.length<2){ msg='Busbar needs 1 parent + its children selected (≥2 tiles).'; render(); return; }
  const byRow={}; for(const id of tiles){ const r=rowOf(ents[id]); (byRow[r]=byRow[r]||[]).push(id); }
  const rows=Object.keys(byRow).map(Number).sort((a,b)=>a-b);
  if(rows.length!==2 || byRow[rows[0]].length!==1 || rows[1]!==rows[0]+1){
    msg='Busbar needs exactly 1 parent and its children in the row directly below it.'; render(); return; }
  const parent=byRow[rows[0]][0], kids=byRow[rows[1]].sort((a,b)=>center(ents[a])[0]-center(ents[b])[0]);
  const kcx=kids.map(k=>center(ents[k])[0]), c1=kcx[0], cn=kcx[kcx.length-1], pcx=(c1+cn)/2;
  ents[parent].x = pcx-CW/2;                                 // centre the parent over C1..Cn
  const busY=ents[parent].y+CH+GAP/2;                        // halfway parent-bottom ↔ child-top (= gap centre)
  const mk=o=>{ const id='seg'+(++segN); ents[id]={id,anchor:parent,...o}; };   // every new line is anchored to the parent
  if(kids.length===1){                                       // single child: one full-gap vertical, no busbar
    mk({type:'vseg',x:pcx,y1:ents[parent].y+CH,y2:ents[kids[0]].y});
  } else {
    mk({type:'hseg',y:busY,x1:c1,x2:cn});                    // busbar
    mk({type:'vseg',x:pcx,y1:ents[parent].y+CH,y2:busY});    // parent drop
    for(let i=0;i<kids.length;i++) mk({type:'vseg',x:kcx[i],y1:busY,y2:ents[kids[i]].y});   // child drops
  }
  const anc=new Set(ancestors(parent));                      // anchor every still-FREE child to the parent
  let nf=0; for(const k of kids) if(ents[k].anchor===null && !anc.has(k)){ ents[k].anchor=parent; nf++; }  // (keep existing anchors; skip would-be cycles)
  selSet.clear(); msg=`Busbar: ${parent} → ${kids.length} child(ren); anchored the new lines + ${nf} free child(ren) to ${parent}.`; render();
}

// ---- Marriage: a horizontal line between two same-row tiles (left-tile right edge ↔ right-tile left edge) ----
function drawMarriage(){
  const tiles=[...selSet].filter(id=>ents[id]&&ents[id].type==='tile');
  if(tiles.length!==2){ msg='Marriage needs exactly 2 tiles selected.'; render(); return; }
  const [a,b]=tiles.sort((p,q)=>center(ents[p])[0]-center(ents[q])[0]);   // a = left, b = right
  if(rowOf(ents[a])!==rowOf(ents[b])){ msg='Marriage: both tiles must be in the same row.'; render(); return; }
  const id='seg'+(++segN); ents[id]={id,type:'hseg',anchor:null,y:ents[a].y+CH/2,x1:ents[a].x+CW,x2:ents[b].x};
  selSet.clear(); msg=`Marriage line: ${a} — ${b}.`; render();
}

function vc(){ return [(wrap.scrollLeft+wrap.clientWidth/2)/scale,(wrap.scrollTop+wrap.clientHeight/2)/scale]; }
document.getElementById('addH').onclick=()=>{ const[cx,cy]=vc(),id='seg'+(++segN);
  ents[id]={id,type:'hseg',anchor:null,y:snapHY(cy),x1:cx-CW,x2:cx+CW}; render(); };
document.getElementById('addV').onclick=()=>{ const[cx,cy]=vc(),id='seg'+(++segN);
  const r=Math.max(0,Math.round((cy-CH)/PITCH));             // V line = GAP/2 tall: tile-bottom → gap-centre (1/2 the short gap-cell)
  ents[id]={id,type:'vseg',anchor:null,x:cx,y1:r*PITCH+CH,y2:r*PITCH+CH+GAP/2}; render(); };
document.getElementById('pack').onclick=packSubtrees;
document.getElementById('bus').onclick=drawBusbar;
document.getElementById('mar').onclick=drawMarriage;
document.getElementById('del').onclick=delLines;
document.getElementById('zi').onclick=()=>{scale=Math.min(2,scale*1.25);render();};
document.getElementById('zo').onclick=()=>{scale=Math.max(0.05,scale/1.25);render();};
document.getElementById('save').onclick=()=>{
  let y='# semi-manual positions. each entity has an optional anchor (one max). px coords; tiles also row.\n';
  y+=`cell: {w: ${CW}, h: ${CH}, pitch: ${PITCH}}\nentities:\n`;
  for(const id in ents){ const e=ents[id], a=e.anchor||'~';
    let geo = e.type==='tile' ? `x: ${Math.round(e.x)}, row: ${Math.round(e.y/PITCH)}`
            : e.type==='hseg' ? `y: ${Math.round(e.y)}, x1: ${Math.round(e.x1)}, x2: ${Math.round(e.x2)}`
            :                   `x: ${Math.round(e.x)}, y1: ${Math.round(e.y1)}, y2: ${Math.round(e.y2)}`;
    y+=`  ${JSON.stringify(id)}: {type: ${e.type}, anchor: ${a}, ${geo}}\n`; }
  const b=new Blob([y],{type:'text/yaml'}), a=document.createElement('a');
  a.href=URL.createObjectURL(b); a.download='positions.yaml'; a.click();
};
</script></body></html>"""
