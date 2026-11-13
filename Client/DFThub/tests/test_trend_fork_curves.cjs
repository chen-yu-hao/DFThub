const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/replica/analyzeView.js'), 'utf8');
const implementation = ['weightGroups', 'trendRoot', 'trendColumns', 'trendLinks', 'trendDomain'].map(name => source.match(new RegExp('  function ' + name + '\\([^]*?\\n  }'))[0]).join('\n');
const runs = [];
for (let weight = 0; weight < 4; weight++) {
 const id=`weight_${weight}`;
 runs.push({id,runId:id,jobId:'a',kind:'weight',parent:null,effectiveWeight:.02*2**weight,value:7});
 runs.push({id:id+'/fork-1',runId:id+'/fork-1',jobId:'a',kind:'fork',parent:id,effectiveWeight:.02*2**weight,value:5});
 if(weight===1||weight===2)runs.push({id:id+'/fork-2',runId:id+'/fork-2',jobId:'a',kind:'fork',parent:id+'/fork-1',effectiveWeight:.02*2**weight,value:4});
}
function model(all=runs){return new Function('RUNS','BY_ID','plottable',implementation+'\nreturn {trendRoot,trendColumns,trendLinks};')(all,Object.fromEntries(all.map(r=>[r.id,r])),v=>Number.isFinite(v));}
const {trendColumns,trendLinks,trendRoot}=model();
const columns=trendColumns(runs), series={matches:()=>true,get:r=>r.value};
assert.equal(columns.length,4);
assert.deepEqual(columns.map(c=>c.weight),[.16,.08,.04,.02]);
const edges=trendLinks(series,runs,columns);
assert.deepEqual(edges.main.map(e=>e.map(r=>r.id)),[['weight_3','weight_2'],['weight_2','weight_1'],['weight_1','weight_0']]);
assert.equal(edges.branches.length,6);
for(const [parent,run] of edges.branches){assert.equal(parent.id,run.parent);assert.equal(trendRoot(parent).id,trendRoot(run).id);}
for(const col of columns)for(const family of col.families){const order=family.order.map(r=>r.id);for(const run of family.order.slice(1))assert(order.indexOf(run.parent)<order.indexOf(run.id));}
const withoutParent=runs.filter(r=>r.id!=='weight_1/fork-1');
const partial=trendLinks(series,withoutParent,trendColumns(withoutParent));
assert(!partial.branches.some(([,r])=>r.id==='weight_1/fork-2'),'excluded parent must not be replaced by a grandparent');
assert.equal(trendRoot(runs.find(r=>r.id==='weight_1/fork-2')).id,'weight_1');
const missing={...series,get:r=>r.id==='weight_2'?null:r.value};
assert(!trendLinks(missing,runs,columns).branches.some(([p])=>p.id==='weight_2'));
const multi=runs.concat(runs.map(r=>({...r,id:'b::'+r.id,parent:r.parent?'b::'+r.parent:null,jobId:'b'})));
const multiModel=model(multi);const multiEdges=multiModel.trendLinks(series,multi,multiModel.trendColumns(multi));
assert.equal(multiEdges.main.length,6);assert.equal(multiEdges.branches.length,12);
for(const [a,b] of [...multiEdges.main,...multiEdges.branches])assert.equal(a.jobId,b.jobId);
const tickSource=source.match(/  function tickText\([^]*?\n  }/)[0];
const tickText=new Function(tickSource+'\nreturn tickText;')();
assert.equal(tickText(.25,.25),'0.25');assert.equal(tickText(.0025,.0025),'0.0025');
console.log('PASS reference semantics: main runs only, actual-parent fork branches, stable ordering, missing/filtered parents, job isolation and exact ticks');
