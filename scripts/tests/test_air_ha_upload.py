"""Execute the production minute buffer, JSON protocol and retry logic on host."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'main/boards/custom/waveshare-air-monitor-1.8-v1'


class AirHaUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.binary = cls.directory/'air_ha_test'
        compiler = shlex.split(os.environ.get('CXX','c++'))
        candidates = [Path(os.environ.get('AIR_CJSON_DIR','/nonexistent')),
                      ROOT/'managed_components/espressif__cjson/cJSON',
                      Path(os.environ.get('IDF_PATH','/nonexistent'))/'components/json/cJSON',
                      Path.home()/'esp/esp-idf/components/json/cJSON']
        cls.json_dir = next((p for p in candidates if (p/'cJSON.c').is_file()),None)
        if not cls.json_dir: raise RuntimeError('Set AIR_CJSON_DIR to a cJSON source directory')
        source = cls.directory/'test.cc'
        source.write_text(r'''
#include "air_ha_model.h"
#include "air_ha_protocol.h"
#include <cJSON.h>
#include <cassert>
#include <cstdlib>
#include <cmath>
#include <iostream>
#include <string>
using namespace air;
int allocation_budget=0;
void* LimitedMalloc(size_t n) { return allocation_budget-- > 0 ? std::malloc(n) : nullptr; }
AirSnapshot Frame(uint64_t t) {
    AirSnapshot s{}; s.now_ms=t;
    s.co2.has_value=s.co2.has_frame=s.co2.connected=s.co2.ready=s.co2.within_spec=true;
    s.co2.last_frame_ms=s.co2.last_value_ms=t/5000*5000;
    s.hcho.has_value=s.hcho.has_frame=s.hcho.connected=s.hcho.ready=s.hcho.within_spec=true;
    s.hcho.last_frame_ms=s.hcho.last_value_ms=t;
    s.scd={static_cast<uint16_t>(600+10*(t/5000%12)),24,45};
    s.sfa.ppb=10+t/1000%60; return s;
}
void Minute(HaMinuteBuffer& b,uint64_t base=0) {
    for(uint64_t i=0;i<60;i++) b.Observe(Frame(base+i*1000));
    b.Observe(Frame(base+60000));
}
HaMinute Front(const HaMinuteBuffer& b) { HaMinute r; assert(b.CopyBatch(std::span(&r,1))==1); return r; }
int main(int argc,char** argv) {
 assert(argc==2); std::string mode=argv[1]; HaMinuteBuffer b;
 if(mode=="minute") {
  Minute(b); auto r=Front(b); assert(r.metrics[0].count==12 && r.metrics[1].count==60);
  assert(r.metrics[2].count==12 && r.metrics[3].count==12);
  assert(r.metrics[0].Mean()==655 && r.metrics[0].minimum==600 && r.metrics[0].maximum==710);
  assert(r.first_ms==0 && r.last_ms==59000 && r.sequence==1);
 } else if(mode=="late-frame") {
  for(uint64_t t=0;t<55000;t+=1000)b.Observe(Frame(t));
  auto s=Frame(60010);s.co2.last_value_ms=55000;s.hcho.last_value_ms=59999;b.Observe(s);
  auto r=Front(b);assert(r.metrics[0].count==12 && r.metrics[1].count==56 && r.last_ms==59999);
  b.Observe(Frame(61000));b.Flush(62000);uint32_t seq=1;b.Acknowledge(std::span(&seq,1));
  assert(Front(b).first_ms>=60000);
 } else if(mode=="duplicate") {
  auto s=Frame(1000); for(int i=0;i<100;i++) b.Observe(s); b.Flush(2000);
  assert(Front(b).metrics[0].count==1 && Front(b).metrics[1].count==1);
 } else if(mode=="invalid") {
  auto s=Frame(1000); s.co2.ready=false; s.hcho.within_spec=false; b.Observe(s);
  s=Frame(6000); s.scd.temperature=NAN; s.sfa.ppb=1001; b.Observe(s); b.Flush(7000);
  auto r=Front(b); assert(r.metrics[0].count==1 && r.metrics[1].count==0 && r.metrics[2].count==0);
 } else if(mode=="failure-does-not-repeat") {
  b.Observe(Frame(1000)); auto s=Frame(2000); s.co2.last_value_ms=0; s.hcho.last_value_ms=1000;
  s.co2.connected=s.hcho.connected=false; b.Observe(s); b.Flush(3000);
  assert(Front(b).metrics[0].count==1 && Front(b).metrics[1].count==1);
 } else if(mode=="partial") {
  b.Observe(Frame(1000)); b.Observe(Frame(31000)); b.Flush(32000);
  auto r=Front(b); assert(r.first_ms==0 && r.last_ms==31000 && r.last_ms-r.first_ms<=60000);
 } else if(mode=="gap") {
  b.Observe(Frame(1000)); b.Observe(Frame(3600000)); assert(b.size()==1);
  b.Flush(3601000); assert(b.size()==2 && Front(b).last_ms<60000);
 } else if(mode=="empty-minute") {
  AirSnapshot s{}; s.now_ms=1000; b.Observe(s); s.now_ms=60000; b.Observe(s);
  auto r=Front(b); assert(r.metrics[0].count==0 && r.first_ms==0 && r.last_ms<60000);
 } else if(mode=="overflow") {
  for(size_t i=0;i<HaMinuteBuffer::kCapacity+5;i++) Minute(b,i*60000);
  assert(b.size()==HaMinuteBuffer::kCapacity && b.dropped()>0 && Front(b).sequence==1);
 } else if(mode=="ack") {
  Minute(b); Minute(b,60000); uint32_t wrong=2; assert(!b.Acknowledge(std::span(&wrong,1)) && b.size()==2);
  uint32_t good=1; assert(b.Acknowledge(std::span(&good,1)) && Front(b).sequence==2);
 } else if(mode=="clock") {
  HaUtcClock c; assert(!c.ToEpochMs(1000)); assert(c.Synchronize("Sat, 24 Oct 2026 10:00:00 GMT",60000));
  assert(c.ToEpochMs(0).value()==1792835940000LL);
  assert(HaIso8601(c.ToEpochMs(59000).value())=="2026-10-24T09:59:59.000Z");
  assert(!c.Synchronize("Sat, 99 Oct 2026 10:00:00 GMT",60000));
  assert(!c.Synchronize("Sat, 24 Xxx 2026 10:00:00 GMT",60000));
 } else if(mode=="solar-location") {
  auto location=ParseHaSolarLocation(R"({"solar_location":{"latitude":39.904,"longitude":116.407}})");
  assert(location && location->latitude_e6==39904000 && location->longitude_e6==116407000);
  assert(ParseHaSolarLocation(R"({"solar_location":{"latitude":0,"longitude":0}})"));
  for(const auto& json:{"{}", "null", "[]", R"({"solar_location":null})",
    R"({"solar_location":{"latitude":91,"longitude":0}})",
    R"({"solar_location":{"latitude":0,"longitude":-181}})",
    R"({"solar_location":{"latitude":true,"longitude":0}})",
    R"({"solar_location":{"latitude":"39","longitude":0}})",
    R"({"solar_location":{"latitude":1e999,"longitude":0}})",
    R"({"solar_location":{"latitude":0}})",
    R"({"solar_location":{"latitude":0,"longitude":0}}junk)"})
    assert(!ParseHaSolarLocation(json));
 } else if(mode=="retry") {
  HaRetry r; assert(r.Due(0)); r.Failure(0,0); assert(!r.Due(4999) && r.Due(5000));
  r.Failure(5000,0); assert(r.Due(15000) && !r.Due(14999));
  for(int i=0;i<100;i++) r.Failure(100000,0); assert(!r.Due(399999) && r.Due(400000));
  r.Reconnected(200000); assert(r.Due(200000)); r.Success(200000); assert(r.Due(202000) && !r.Due(201999));
 } else if(mode=="frozen" || mode=="bad-ack" || mode=="generate") {
  Minute(b); HaUtcClock c; assert(c.Synchronize("Sat, 24 Oct 2026 10:00:00 GMT",60000));
  HaBatch flight; assert(flight.Capture(b)); assert(flight.Encode("air_monitor_01","boot-test",c));
  const auto original=flight.body();
  if(mode=="generate") { std::cout<<original; return 0; }
  if(mode=="frozen") {
   c.Synchronize("Sat, 24 Oct 2026 10:01:00 GMT",60000); Minute(b,60000);
   assert(flight.Capture(b) && flight.Encode("air_monitor_01","boot-test",c));
   assert(flight.body()==original && b.size()==2);
   assert(flight.CheckAck(R"({"schema_version":2,"device_id":"air_monitor_01","session_id":"boot-test","accepted":[1]})","air_monitor_01","boot-test"));
   assert(flight.Commit(b) && b.size()==1 && Front(b).sequence==2);
  } else {
   for(const auto& ack:{"{}",R"({"schema_version":2,"device_id":"air_monitor_01","session_id":"boot-test","accepted":[]})",
    R"({"schema_version":2,"device_id":"other","session_id":"boot-test","accepted":[1]})",
    R"({"schema_version":2,"device_id":"air_monitor_01","session_id":"boot-old","accepted":[1]})",
    R"({"schema_version":2,"device_id":"air_monitor_01","session_id":"boot-test","accepted":[2]})",
    R"({"schema_version":2,"device_id":"air_monitor_01","session_id":"boot-test","accepted":[1,1]})"})
     assert(!flight.CheckAck(ack,"air_monitor_01","boot-test") && b.size()==1);
  }
 } else if(mode=="oom") {
  Minute(b);HaUtcClock clock;clock.Synchronize("Sat, 24 Oct 2026 10:00:00 GMT",60000);
  for(int budget=0;budget<200;budget++) {
   HaBatch flight;flight.Capture(b);allocation_budget=budget;
   cJSON_Hooks hooks{LimitedMalloc,std::free};cJSON_InitHooks(&hooks);
   bool encoded=flight.Encode("air_monitor_01","boot-test",clock);cJSON_InitHooks(nullptr);
   if(!encoded) { assert(flight.body().empty());continue; }
   auto* root=cJSON_Parse(flight.body().c_str());assert(root && cJSON_GetArraySize(root)==4);
   auto* record=cJSON_GetArrayItem(cJSON_GetObjectItem(root,"records"),0);
   assert(cJSON_GetArraySize(record)==9);
   for(const auto& name:{"co2_ppm","hcho_ppb","temperature_c","humidity_pct"})
    assert(cJSON_GetArraySize(cJSON_GetObjectItem(record,name))==4);
   cJSON_Delete(root);
  }
 } else if(mode=="unsynced") {
  Minute(b); HaBatch flight; HaUtcClock clock; flight.Capture(b); flight.Encode("air_monitor_01","boot-test",clock);
  assert(flight.body().find("\"clock_quality\":\"unsynced\"")!=std::string::npos);
 } else { assert(false); }
}
''')
        cobject=cls.directory/'cJSON.o'
        subprocess.run(compiler+['-x','c','-std=c11','-fsanitize=address,undefined','-c',str(cls.json_dir/'cJSON.c'),'-o',str(cobject)],check=True,capture_output=True,text=True)
        compiled=subprocess.run(compiler+['-std=c++20','-fsanitize=address,undefined','-fno-omit-frame-pointer',
            '-I'+str(BOARD),'-I'+str(cls.json_dir),str(source),str(BOARD/'air_ha_model.cc'),
            str(BOARD/'air_ha_protocol.cc'),str(cobject),'-o',str(cls.binary)],capture_output=True,text=True)
        if compiled.returncode: raise AssertionError(compiled.stdout+compiled.stderr)

    def run_mode(self,mode):
        result=subprocess.run([str(self.binary),mode],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout

    def test_wire_output_validates_in_actual_ha_core(self):
        import importlib.util,sys
        path=ROOT/'homeassistant/custom_components/air_monitor/core.py'
        spec=importlib.util.spec_from_file_location('air_firmware_contract',path)
        core=importlib.util.module_from_spec(spec);sys.modules[spec.name]=core;spec.loader.exec_module(core)
        payload=json.loads(self.run_mode('generate'))
        batch=core.validate_batch(payload,'air_monitor_01',1792836000)
        with tempfile.TemporaryDirectory() as directory:
            store=core.UploadStore(Path(directory)/'minutes.sqlite3');store.initialize()
            first=store.save(batch,1792836000,120);retry=store.save(batch,1792836001,120)
            self.assertEqual(first['accepted'],[1]);self.assertEqual(retry['duplicates'],1)
            self.assertEqual(store.latest('air_monitor_01')['co2_ppm']['count'],12)

def mode_test(name):
    def test(self):
        self.run_mode(name)
    return test

for name in ('minute','late-frame','duplicate','invalid','failure-does-not-repeat','partial','gap','empty-minute',
             'overflow','ack','clock','solar-location','retry','frozen','bad-ack','unsynced','oom'):
    setattr(AirHaUploadTests,'test_'+name.replace('-','_'),mode_test(name))

if __name__=='__main__': unittest.main()
