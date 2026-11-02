import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
globalThis.HTMLElement=class {};
globalThis.customElements={get(){return true;},define(){}};
globalThis.window={};
const source=readFileSync(new URL('../www/air-monitor-minute-history.js',import.meta.url),'utf8');
const {minuteSegments, AirMonitorMinuteHistory}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const point=(t,value=800)=>({t,co2_ppm:{mean:value,min:value-20,max:value+20,count:12}});
test('keeps a 40-minute drive at 40 points',()=>assert.equal(minuteSegments(Array.from({length:40},(_,i)=>point(i*60)),'co2_ppm')[0].length,40));
test('does not connect a parked gap',()=>assert.deepEqual(minuteSegments([point(0),point(60),point(3600)],'co2_ppm').map(s=>s.length),[2,1]));
test('invalid measurements break a line rather than becoming zero',()=>assert.deepEqual(minuteSegments([point(0),{t:60,co2_ppm:null},point(120)],'co2_ppm').map(s=>s.length),[1,1]));
test('does not invent points for a parked interval',()=>assert.equal(minuteSegments([],'co2_ppm').length,0));

test('a new range supersedes a pending request without displaying stale data',async()=>{
  const pending=[];
  const rendered=[];
  const card=Object.create(AirMonitorMinuteHistory.prototype);
  Object.assign(card,{isConnected:true,_config:{device_id:'race_test',metric:'co2_ppm'},
    _hass:{user:{id:'test'},callApi:(_method,path)=>new Promise(resolve=>pending.push({path,resolve}))},
    _select:{value:'latest'},_status:{textContent:''},_chart:{replaceChildren(){}},_tooltip:{textContent:''},
    _generation:0,_draw(){rendered.push(this._points);}});
  const first=card._load(true);
  card._select.value='24';
  const second=card._load(true);
  assert.equal(pending.length,2,'range change must start the new query immediately');
  pending[0].resolve({points:[{t:1}]});
  await first;
  assert.equal(card._loading,true,'old response must not clear the new request loading state');
  assert.equal(rendered.length,0,'old response must not be rendered');
  pending[1].resolve({points:[{t:2}]});
  await second;
  assert.deepEqual(rendered,[[{t:2}]]);
});
