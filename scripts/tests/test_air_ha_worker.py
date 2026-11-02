"""Run the actual ESP worker against a deterministic network/task fault harness."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
BOARD=ROOT/'main/boards/custom/waveshare-air-monitor-1.8-v1'

class AirHaWorkerTests(unittest.TestCase):
    def test_offline_retries_slow_http_and_backfill(self):
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory)
            common=r'''
#pragma once
#include <cstdint>
#include <cstddef>
using esp_err_t=int;
constexpr int ESP_OK=0,ESP_FAIL=-1,pdPASS=1,MALLOC_CAP_SPIRAM=1,MALLOC_CAP_8BIT=2;
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define pdMS_TO_TICKS(x) (x)
int64_t esp_timer_get_time(); uint32_t esp_random();
void* heap_caps_malloc(size_t,int);void heap_caps_free(void*);
int xTaskCreate(void(*)(void*),const char*,unsigned,void*,unsigned,void*);
void vTaskDelay(unsigned);void vTaskDelete(void*);
class WifiManager {public:static WifiManager& GetInstance();bool IsConnected();bool IsConfigMode();};
int esp_crt_bundle_attach(void*);
enum { HTTP_METHOD_POST,HTTP_METHOD_HEAD,HTTP_EVENT_ON_HEADER,HTTP_EVENT_ON_DATA };
struct esp_http_client_event_t {int event_id;void* user_data;char* header_key;char* header_value;void* data;int data_len;};
struct esp_http_client_config_t {
 const char* url;int method;int timeout_ms;bool disable_auto_redirect;
 int(*crt_bundle_attach)(void*);esp_err_t(*event_handler)(esp_http_client_event_t*);void* user_data;
};
struct Client;using esp_http_client_handle_t=Client*;
Client* esp_http_client_init(const esp_http_client_config_t*);
int esp_http_client_set_header(Client*,const char*,const char*);
int esp_http_client_set_post_field(Client*,const char*,int);
int esp_http_client_perform(Client*);int esp_http_client_get_status_code(Client*);int esp_http_client_cleanup(Client*);
'''
            (d/'fake_runtime.h').write_text(common)
            for name in ('esp_crt_bundle.h','esp_heap_caps.h','esp_http_client.h','esp_log.h','esp_random.h',
                         'esp_timer.h','freertos/FreeRTOS.h','freertos/task.h','wifi_manager.h'):
                p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('#include "fake_runtime.h"\n')
            (d/'air_ha_credentials.h').write_text('''#pragma once
namespace air::ha_config { constexpr bool kEnabled=true;
constexpr char kEndpoint[]="https://example.org/ingest", kDevice[]="air_monitor_01",kKey[]="host-test-key"; }
''')
            source=d/'worker.cc'
            source.write_text(r'''
#include "fake_runtime.h"
#include "air_ha_upload.h"
#include <cJSON.h>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <string>
#include <vector>
using namespace air;
static uint64_t now_ms=0,next_frame=0;
static AirHaUpload* upload;
static void(*task)(void*);static void* task_ctx;
static std::vector<void*> allocations;
static std::vector<std::string> posts;
static bool stopped=false;
static int solar_updates=0;
struct Done {};
AirSnapshot Frame(uint64_t t) {
 AirSnapshot s{};s.now_ms=t;
 s.co2.has_value=s.co2.connected=s.co2.ready=s.co2.within_spec=true;
 s.hcho.has_value=s.hcho.connected=s.hcho.ready=s.hcho.within_spec=true;
 s.co2.last_value_ms=t/5000*5000;s.hcho.last_value_ms=t;
 s.scd={800,24,45};s.sfa.ppb=20;return s;
}
void Advance(uint64_t delta) {
 const auto target=now_ms+delta;
 while(next_frame<=target) {now_ms=next_frame;upload->Observe(Frame(now_ms));next_frame+=1000;}
 now_ms=target;
 if(now_ms>=240000 && !stopped) {stopped=true;upload->Stop();upload->FinishCollection(now_ms);}
}
int64_t esp_timer_get_time(){return now_ms*1000;}
uint32_t esp_random(){return 42;}
void* heap_caps_malloc(size_t n,int){void* p=malloc(n);allocations.push_back(p);return p;}
void heap_caps_free(void* p){free(p);}
int xTaskCreate(void(*fn)(void*),const char*,unsigned,void* ctx,unsigned,void*){task=fn;task_ctx=ctx;return pdPASS;}
void vTaskDelay(unsigned ms){Advance(ms);}
void vTaskDelete(void*){throw Done{};}
WifiManager& WifiManager::GetInstance(){static WifiManager wifi;return wifi;}
bool WifiManager::IsConnected(){return now_ms>=120000;}
bool WifiManager::IsConfigMode(){return false;}
int esp_crt_bundle_attach(void*){return 0;}
struct Client{esp_http_client_config_t config;std::string body;std::map<std::string,std::string> headers;int status=0;};
Client* esp_http_client_init(const esp_http_client_config_t* c){
 assert(c->disable_auto_redirect && c->crt_bundle_attach==esp_crt_bundle_attach && c->timeout_ms>0 && c->timeout_ms<=5000);
 assert(std::string(c->url).starts_with("https://"));return new Client{*c};
}
int esp_http_client_set_header(Client* c,const char* k,const char* v){c->headers[k]=v;return ESP_OK;}
int esp_http_client_set_post_field(Client* c,const char* b,int n){c->body.assign(b,n);return ESP_OK;}
void Emit(Client* c,std::string data){
 esp_http_client_event_t event{HTTP_EVENT_ON_DATA,c->config.user_data,nullptr,nullptr,data.data(),int(data.size())};
 c->config.event_handler(&event); // Like a transport, may ignore callback failure.
}
int esp_http_client_perform(Client* c){
 if(c->config.method==HTTP_METHOD_HEAD){
  Advance(2000);char key[]="Date",date[]="Sat, 24 Oct 2026 10:00:02 GMT";
  esp_http_client_event_t event{HTTP_EVENT_ON_HEADER,c->config.user_data,key,date,nullptr,0};
  c->config.event_handler(&event);c->status=405;return ESP_OK;
 }
 assert(c->headers["Authorization"]=="Bearer host-test-key");
 assert(c->headers["X-Air-Monitor-Device"]=="air_monitor_01");
 assert(c->headers["Content-Type"]=="application/json");
 posts.push_back(c->body);Advance(4000);
 auto* root=cJSON_Parse(c->body.c_str());assert(root);
 auto* ack=cJSON_CreateObject();cJSON_AddNumberToObject(ack,"schema_version",2);
 cJSON_AddStringToObject(ack,"device_id","air_monitor_01");
 const char* session=cJSON_GetObjectItem(root,"session_id")->valuestring;
 cJSON_AddStringToObject(ack,"session_id",posts.size()==2?"wrong-boot":session);
 auto* location=cJSON_AddObjectToObject(ack,"solar_location");
 cJSON_AddNumberToObject(location,"latitude",39.904);
 cJSON_AddNumberToObject(location,"longitude",116.407);
 auto* accepted=cJSON_AddArrayToObject(ack,"accepted");
 auto* records=cJSON_GetObjectItem(root,"records");
 for(int i=0;i<cJSON_GetArraySize(records);i++)
  cJSON_AddItemToArray(accepted,cJSON_CreateNumber(cJSON_GetObjectItem(cJSON_GetArrayItem(records,i),"seq")->valuedouble));
 char* text=cJSON_PrintUnformatted(ack);std::string body=text;cJSON_free(text);cJSON_Delete(ack);cJSON_Delete(root);
 c->status=posts.size()==3?500:200;
 if(posts.size()==4) { Emit(c,body);Emit(c,std::string(5000,' ')); }
 else Emit(c,body);
 return posts.size()==1?ESP_FAIL:ESP_OK; // ACK lost after server may already save it.
}
int esp_http_client_get_status_code(Client* c){return c->status;}
int esp_http_client_cleanup(Client* c){delete c;return ESP_OK;}
int main(){
 AirHaUpload instance;upload=&instance;assert(instance.Start([](std::optional<SolarLocation> location,int64_t utc,uint64_t uptime) {
  assert(posts.size()>=5 && "failed, wrong-session and oversized responses must not update location");
  assert(location && location->latitude_e6==39904000 && location->longitude_e6==116407000);
  assert(utc==1792836000000LL+int64_t(uptime-120000));++solar_updates;
 }));Advance(120000);
 try {task(task_ctx);} catch(const Done&){}
 assert(instance.stopped() && posts.size()>=6 && solar_updates>0);
 for(int i=1;i<5;i++) assert(posts[i]==posts[0]);
 for(const auto& body:posts) std::cout<<body<<'\n';
 for(void* p:allocations)free(p);
}
''')
            compiler=shlex.split(os.environ.get('CXX','c++'))
            candidates=[Path(os.environ.get('AIR_CJSON_DIR','/nonexistent')),
                        ROOT/'managed_components/espressif__cjson/cJSON',
                        Path(os.environ.get('IDF_PATH','/nonexistent'))/'components/json/cJSON',
                        Path.home()/'esp/esp-idf/components/json/cJSON']
            json_dir=next(p for p in candidates if (p/'cJSON.c').is_file())
            obj=d/'cJSON.o'
            subprocess.run(compiler+['-x','c','-std=c11','-fsanitize=address,undefined','-c',str(json_dir/'cJSON.c'),'-o',str(obj)],check=True,capture_output=True,text=True)
            command=compiler+['-std=c++20','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                '-I'+str(d),'-I'+str(BOARD),'-I'+str(json_dir),str(source),str(BOARD/'air_ha_model.cc'),
                str(BOARD/'air_ha_protocol.cc'),str(BOARD/'air_ha_upload.cc'),str(obj),'-o',str(d/'worker')]
            built=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(d/'worker')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            path=ROOT/'homeassistant/custom_components/air_monitor/core.py'
            spec=importlib.util.spec_from_file_location('ha_worker_contract',path)
            core=importlib.util.module_from_spec(spec);sys.modules[spec.name]=core;spec.loader.exec_module(core)
            store=core.UploadStore(d/'history.sqlite3');store.initialize()
            unique={}
            for line in result.stdout.splitlines():
                payload=json.loads(line)
                batch=core.validate_batch(payload,'air_monitor_01',1792836600)
                store.save(batch,1792836600,120)
                for record in payload['records']:unique[record['seq']]=record
            self.assertGreaterEqual(len(unique),4)
            for seq in (1,2,3,4):
                self.assertEqual(unique[seq]['co2_ppm']['count'],12)
                self.assertEqual(unique[seq]['hcho_ppb']['count'],60)
            self.assertEqual(unique[1]['period_start'],'2026-10-24T09:58:00.000Z')
            self.assertEqual(unique[3]['period_start'],'2026-10-24T10:00:00.000Z')

if __name__=='__main__':unittest.main()
