"""Host checks with sanitizers; hardware/SDK calls are deterministic fakes.

Run: python3 esp32/tests/memory_pause_test.py
Optional: --ssh-header /path/to/old/ssh_client.h checks the old lifecycle too.
Only source headers are copied; real credentials are never included.
"""
import argparse
import re
from pathlib import Path
import subprocess
import tempfile

MAIN = Path(__file__).resolve().parents[1] / "main"

PLATFORM = r'''
#pragma once
#include <atomic>
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <set>
#include <string>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <unistd.h>
#include <fcntl.h>

inline uint32_t clockMs = 0;
inline uint32_t millis() { return clockMs; }
struct SerialFake {
    std::string text;
    void printf(const char* fmt, ...) {
        char line[2048]; va_list ap; va_start(ap, fmt);
        vsnprintf(line, sizeof(line), fmt, ap); va_end(ap); text += line;
    }
    void println(const char* s) { text += s; text += '\n'; }
    size_t write(const uint8_t* s, size_t n) { text.append((const char*)s, n); return n; }
};
inline SerialFake Serial;

using BaseType_t = int;
using TaskHandle_t = void*;
using TickType_t = uint32_t;
constexpr int pdPASS = 1, pdTRUE = 1;
constexpr uint32_t portMAX_DELAY = UINT32_MAX;
#define pdMS_TO_TICKS(x) (x)
#define CONFIG_ARDUINO_LOOP_STACK_SIZE 8192
#define configTICK_RATE_HZ 1000
struct portMUX_TYPE {};
#define portMUX_INITIALIZER_UNLOCKED {}
#define portENTER_CRITICAL_SAFE(x) ((void)(x))
#define portEXIT_CRITICAL_SAFE(x) ((void)(x))
inline uint32_t stackRemaining = 4096;
inline uint32_t uxTaskGetStackHighWaterMark(TaskHandle_t) { return stackRemaining; }
struct Semaphore { bool ready = false; };
using SemaphoreHandle_t = Semaphore*;
inline bool failSemaphore = false, failTask = false, taskActive = false;
inline int taskCreates = 0;
inline void (*pumpFunction)(void*) = nullptr;
inline void* pumpArgument = nullptr;
inline SemaphoreHandle_t xSemaphoreCreateBinary() { return failSemaphore ? nullptr : new Semaphore; }
inline void vSemaphoreDelete(SemaphoreHandle_t s) { assert(!taskActive); delete s; }
inline int xSemaphoreTake(SemaphoreHandle_t s, uint32_t) {
    assert(s); if (!s->ready) return 0; s->ready = false; return pdTRUE;
}
inline void xSemaphoreGive(SemaphoreHandle_t s) { assert(s); s->ready = true; }
inline int xTaskCreate(void (*fn)(void*), const char*, uint32_t, void* arg, int, TaskHandle_t* h) {
    if (failTask) return 0;
    assert(!taskActive && "starting a second bridge before the first exits");
    taskActive = true; ++taskCreates; pumpFunction = fn; pumpArgument = arg;
    *h = reinterpret_cast<void*>(1); return pdPASS;
}
inline void vTaskDelete(TaskHandle_t) { taskActive = false; }
void vTaskDelay(uint32_t duration);
inline void finishPump() {
    assert(taskActive); pumpFunction(pumpArgument); pumpArgument = nullptr;
    assert(!taskActive);
}

using esp_err_t = int;
constexpr int ESP_OK = 0;
constexpr uint32_t MALLOC_CAP_INTERNAL = 1, MALLOC_CAP_8BIT = 2, MALLOC_CAP_DMA = 4;
inline uint32_t freeHeap = 120000, largestBlock = 80000;
struct multi_heap_info_t {
    size_t total_free_bytes, minimum_free_bytes, largest_free_block;
    size_t total_allocated_bytes, allocated_blocks, free_blocks;
};
inline void heap_caps_get_info(multi_heap_info_t* i, uint32_t) {
    *i = {freeHeap, freeHeap, largestBlock, 50000, 100, 5};
}
inline size_t heap_caps_get_free_size(uint32_t) { return freeHeap; }
inline size_t heap_caps_get_largest_free_block(uint32_t) { return largestBlock; }
inline bool heap_caps_check_integrity_all(bool) { return true; }
inline auto allocHook = static_cast<void (*)(size_t, uint32_t, const char*)>(nullptr);
inline int heap_caps_register_failed_alloc_callback(decltype(allocHook) hook) { allocHook = hook; return ESP_OK; }

// Socket fakes also check descriptor ownership. These macros rename the
// Arduino Client connect method consistently in both its base and subclass.
#define socket fake_socket
#define bind fake_bind
#define getsockname fake_getsockname
#define listen fake_listen
#define connect fake_connect
#define accept fake_accept
#define select fake_select
#define getsockopt fake_getsockopt
#define setsockopt fake_setsockopt
#define close fake_close
#define fcntl fake_fcntl
#define send fake_send
#define recv fake_recv
#define shutdown fake_shutdown
inline std::set<int> descriptors;
inline int nextFd() { int n=10; while(descriptors.count(n)) ++n; descriptors.insert(n); return n; }
inline int fake_socket(int, int, int) { return nextFd(); }
inline int fake_bind(int, const sockaddr*, socklen_t) { return 0; }
inline int fake_getsockname(int, sockaddr*, socklen_t*) { return 0; }
inline int fake_listen(int, int) { return 0; }
inline int fake_connect(int, const sockaddr*, socklen_t) { return 0; }
inline int fake_accept(int, sockaddr*, socklen_t*) { return nextFd(); }
inline int fake_select(int, fd_set*, fd_set*, fd_set*, timeval*) { return 1; }
inline int fake_getsockopt(int, int, int, void* result, socklen_t*) { *(int*)result=0; return 0; }
inline int fake_setsockopt(int, int, int, const void*, socklen_t) { return 0; }
inline int fake_close(int fd) { assert(descriptors.erase(fd)==1); return 0; }
inline int fake_fcntl(int, int, ...) { return 0; }
inline int fake_send(int, const void*, size_t n, int) { return n; }
inline int fake_recv(int, void*, size_t, int) { return 0; }
inline int fake_shutdown(int fd, int) { return descriptors.count(fd) ? 0 : -1; }
struct IPAddress {};
class Client {
public:
    virtual ~Client() = default;
    virtual int connect(IPAddress, uint16_t) = 0;
    virtual int connect(const char*, uint16_t) = 0;
    virtual size_t write(uint8_t) = 0;
    virtual size_t write(const uint8_t*, size_t) = 0;
    virtual int available() = 0;
    virtual int read() = 0;
    virtual int read(uint8_t*, size_t) = 0;
    virtual int peek() = 0;
    virtual void flush() = 0;
    virtual void stop() = 0;
    virtual uint8_t connected() = 0;
    virtual operator bool() = 0;
};

struct Session { bool connected = false; };
struct Channel {};
using ssh_session = Session*;
using ssh_channel = Channel*;
using ssh_key = int*;
using socket_t = int;
constexpr int SSH_OK=0, SSH_ERROR=-1, SSH_AGAIN=-2, SSH_EOF=-127, SSH_AUTH_SUCCESS=0, SSH_AUTH_PARTIAL=1;
constexpr int SSH_OPTIONS_HOST=1, SSH_OPTIONS_PORT=2, SSH_OPTIONS_USER=3,
              SSH_OPTIONS_NODELAY=4, SSH_OPTIONS_PROCESS_CONFIG=5, SSH_OPTIONS_FD=6;
inline int sessions=0, channels=0, failConnect=0, failNewAt=0, newCalls=0;
inline ssh_session ssh_new() { if (++newCalls==failNewAt) return nullptr; ++sessions; return new Session; }
inline void ssh_free(ssh_session s) { if(s) { --sessions; delete s; } }
inline int ssh_connect(ssh_session s) { if(failConnect) return SSH_ERROR; s->connected=true; return SSH_OK; }
inline void ssh_disconnect(ssh_session s) { s->connected=false; }
inline int ssh_is_connected(ssh_session s) { return s->connected; }
inline int ssh_options_set(ssh_session, int, const void*) { return SSH_OK; }
inline const char* ssh_get_error(ssh_session) { return "fake error"; }
inline int ssh_get_error_code(ssh_session) { return 1; }
inline int ssh_get_fd(ssh_session) { return -1; }
inline uint32_t ssh_channel_window_size(ssh_channel) { return 8000; }
inline int ssh_pki_import_privkey_base64(const char*, void*, void*, void*, ssh_key*) { return SSH_ERROR; }
inline void ssh_key_free(ssh_key) {}
inline int ssh_userauth_publickey(ssh_session, const char*, ssh_key) { return SSH_AUTH_SUCCESS; }
inline int ssh_userauth_password(ssh_session, const char*, const char*) { return SSH_AUTH_SUCCESS; }
inline ssh_channel ssh_channel_new(ssh_session) { ++channels; return new Channel; }
inline void ssh_channel_free(ssh_channel c) { --channels; delete c; }
inline int ssh_channel_close(ssh_channel) { return SSH_OK; }
inline int ssh_channel_open_forward(ssh_channel, const char*, int, const char*, int) { return SSH_OK; }
inline int ssh_channel_poll(ssh_channel, int) { return SSH_EOF; }
inline int ssh_channel_read(ssh_channel, void*, uint32_t, int) { return 0; }
inline int ssh_channel_write(ssh_channel, const void*, uint32_t n) { return n; }
inline int ssh_channel_is_open(ssh_channel) { return 1; }
inline void ssh_set_blocking(ssh_session, int) {}
'''

TEST = r'''
#include "ssh_client.h"
#include "memory_debug.h"
#include "debug_commands.h"
#include "demo_protocol.h"
#include "telemetry_debug.h"
#include "sampling_debug.h"
#include <cmath>
#include <deque>
#include <vector>

// Exercise the actual sketch's enqueueMotionSample/runControlledPause bodies
// against a deterministic 100 Hz producer and bounded queue, without hardware.
struct sensors_event_t {
    uint32_t timestamp;
    struct { float x,y,z; } acceleration, gyro;
};
enum DemoMode { AUTO, FILE_MODE };
std::atomic<DemoMode> demoMode{AUTO};
constexpr int WL_CONNECTED=3;
struct FakeWiFi { int status() { return WL_CONNECTED; } } WiFi;
struct FakeMqtt { bool online=true; bool connected() { return online; } } client;
std::atomic<uint32_t> requestedPauseMs{0}, recoverySnapshotDue{0};
std::atomic<bool> afterPauseSnapshotPending{false};
std::atomic<uint32_t> queueDrops{0}, enqueueFailures{0};
TelemetryDebug telemetryDebug;
std::deque<TelemetryPacket> samples;
void* telemetryQueue=nullptr;
// QUEUE_CAPACITY is substituted from the real sketch below.
constexpr uint8_t QUEUE_MAX_SIZE=QUEUE_CAPACITY;
int xQueueSend(void*, const TelemetryPacket* p, int) {
    if(samples.size()==QUEUE_MAX_SIZE) return 0;
    samples.push_back(*p); return pdTRUE;
}
int xQueueReceive(void*, TelemetryPacket* p, int) {
    if(samples.empty()) return 0;
    *p=samples.front(); samples.pop_front(); return pdTRUE;
}
size_t uxQueueMessagesWaiting(void*) { return samples.size(); }
bool enqueueMotionSample(const sensors_event_t&,const sensors_event_t&,uint16_t,bool,bool);
void vTaskDelay(uint32_t duration) {
    for(uint32_t elapsed=0;elapsed<duration;elapsed+=10) {
        clockMs+=10;
        sensors_event_t a{clockMs,{1,2,3},{4,5,6}}, g=a;
        assert(enqueueMotionSample(a,g,0,false,false));
    }
}
// ACTUAL_SKETCH_FUNCTIONS

bool failNothrow = false;
void* operator new(size_t size, const std::nothrow_t&) noexcept {
    if (failNothrow) return nullptr;
    try { return ::operator new(size); } catch (...) { return nullptr; }
}

void clean() { assert(sessions==0 && channels==0 && descriptors.empty() && !taskActive); }
void lifecycle() {
    {
        SSHForwardClient c;
        assert(c.connect("test",22));
        for (int n=0;n<100;++n) {
            c.stop(); // The fake bridge deliberately ignores the 500ms wait.
            const int creates=taskCreates, allocations=newCalls;
            assert(!c.connect("test",22));
            assert(taskCreates==creates && newCalls==allocations);
            assert(sessions==1 && channels==1 && taskActive);
            finishPump(); // Only now may the old resources be freed/reused.
            assert(c.connect("test",22));
        }
        c.stop(); finishPump(); c.stop();
    }
    clean();
    { failSemaphore=true; SSHForwardClient c; assert(!c.connect("test",22)); failSemaphore=false; }
    clean();
    { failConnect=1; SSHForwardClient c; assert(!c.connect("test",22)); failConnect=0; }
    clean();
    { failTask=true; SSHForwardClient c; assert(!c.connect("test",22)); failTask=false; }
    clean();
    { failNothrow=true; SSHForwardClient c; assert(!c.connect("test",22)); failNothrow=false; }
    clean();
    {
        SSHForwardClient c;
        failNewAt=newCalls+2; // Stage 2 allocation fails after pump creation.
        assert(!c.connect("test",22));
        assert(taskActive); finishPump(); c.stop(); failNewAt=0;
    }
    clean();
}

DebugCommands::Command line(DebugCommands& parser, const std::string& s) {
    DebugCommands::Command result{DebugCommands::None,0};
    for(char ch:s) { auto next=parser.feed(ch); if(next.kind!=DebugCommands::None) result=next; }
    return result;
}
void commands() {
    DebugCommands parser;
    for (const int ms : {100,300,500,1000}) {
        auto cmd=line(parser,"pause "+std::to_string(ms)+"\r\n");
        assert(cmd.kind==DebugCommands::Pause && cmd.pauseMs==(unsigned)ms);
    }
    for (const auto* bad : {"pause 0\n","pause 99999\n","pause -1\n","pause 100x\n"})
        assert(line(parser,bad).kind==DebugCommands::Invalid);
    assert(line(parser,std::string(1000,'x')+"pause 100\n").kind==DebugCommands::Invalid);
    assert(line(parser,"heap\n").kind==DebugCommands::Heap);
    assert(line(parser,"heapcheck\n").kind==DebugCommands::HeapCheck);
    assert(line(parser,"\r\n").kind==DebugCommands::None);
    // Non-text serial input must not hide trailing garbage after a NUL.
    assert(line(parser,std::string("pause 100\0junk\n",15)).kind==DebugCommands::Invalid);
}

void memoryReports() {
    MemoryDebug::begin(); Serial.text.clear();
    clockMs=1000; MemoryDebug::periodic(); assert(Serial.text.empty());
    allocHook(12345,7,"test"); assert(Serial.text.empty()); // Never print in hook.
    clockMs=2000; MemoryDebug::periodic();
    assert(Serial.text.find("ALLOCATION_FAILED count=1 recent_bytes=12345")!=std::string::npos);
    Serial.text.clear(); clockMs=3000; MemoryDebug::periodic(); assert(Serial.text.empty());
    freeHeap=20000; clockMs=4000; MemoryDebug::periodic();
    assert(Serial.text.find("LOW_HEADROOM")!=std::string::npos);
    Serial.text.clear(); clockMs=5000; MemoryDebug::periodic(); assert(Serial.text.empty());
    freeHeap=120000; clockMs=6000; MemoryDebug::periodic();
    assert(Serial.text.find("warning_cleared")!=std::string::npos);
    // Stack exhaustion is a real zero, not the unknown (-1) sentinel.
    stackRemaining=0; MemoryDebug::sampleStack(MemoryDebug::Sensor);
    Serial.text.clear(); clockMs=7000; MemoryDebug::periodic();
    assert(Serial.text.find("LOW_HEADROOM")!=std::string::npos);
    assert(Serial.text.find("sensor=0/4096")!=std::string::npos);
}

void pauseDiagnostics() {
    TelemetryDebug debug;
    TelemetryDebug::Snapshot state;
    assert(debug.snapshot(state));
    assert(state.operation==TelemetryDebug::Idle);
    {
        TelemetryDebug::Scope pause(debug,TelemetryDebug::ControlledPause,1100);
        debug.record(TelemetryDebug::QueueDrop,70,123);
        assert(debug.snapshot(state));
        assert(state.operation==TelemetryDebug::ControlledPause);
        assert(state.counts[TelemetryDebug::QueueDrop]==70);
        assert(state.details[TelemetryDebug::QueueDrop]==123);
    }
    assert(debug.snapshot(state) && state.operation==TelemetryDebug::Idle);
    assert(state.counts[TelemetryDebug::QueueDrop]==70); // Not cleared by reading.
}

void actualPauses() {
    assert(QUEUE_MAX_SIZE==20); // Queue enlargement is explicitly deferred.
    for(uint32_t duration : {100u,300u,500u,1000u}) {
        samples.clear(); queueDrops.store(0); enqueueFailures.store(0);
        requestedPauseMs.store(duration); Serial.text.clear();
        const uint32_t start=clockMs;
        runControlledPause();
        assert(clockMs-start==duration && requestedPauseMs.load()==0);
        const uint32_t generated=duration/10;
        const uint32_t kept=generated<QUEUE_MAX_SIZE ? generated : QUEUE_MAX_SIZE;
        assert(samples.size()==kept && queueDrops.load()==generated-kept);
        assert(!enqueueFailures.load());
        assert(Serial.text.find("BEGIN requested_ms="+std::to_string(duration))!=std::string::npos);
        assert(Serial.text.find("END actual_ms="+std::to_string(duration))!=std::string::npos);
        assert(afterPauseSnapshotPending.load());
        assert(recoverySnapshotDue.load()==clockMs+5000);
        // A bounded queue retains the newest samples, even after overflow.
        assert(samples.back().timestamp_ms==clockMs);
        assert(samples.front().timestamp_ms==clockMs-(kept-1)*10);
    }
    client.online=false; requestedPauseMs.store(500);
    const uint32_t before=clockMs;
    runControlledPause(); assert(clockMs==before && !requestedPauseMs.load());
    client.online=true;
    samples.clear();
}

std::vector<uint8_t> frame(demo::Header h, const std::vector<uint8_t>& data) {
    std::vector<uint8_t> result(sizeof(h)+data.size()+4);
    memcpy(result.data(),&h,sizeof(h));
    if(!data.empty()) memcpy(result.data()+sizeof(h),data.data(),data.size());
    uint32_t crc=telemetryCrc32(result.data(),result.size()-4);
    memcpy(result.data()+result.size()-4,&crc,4); return result;
}
void demoMemory() {
    demo::Receiver receiver;
    uint8_t output[sizeof(demo::Header)+demo::CHUNK+4];
    // Repeated replacements of abandoned 64KiB transfers must free the old file.
    for (uint32_t id=1;id<=200;++id) {
        demo::Header h{{'D','E','M','O'},demo::FILE_CHUNK,id,0,demo::MAX_FILE,512};
        auto packet=frame(h,std::vector<uint8_t>(512,0x5a));
        assert(receiver.handle(packet.data(),packet.size(),true,false,output,0));
        assert(receiver.handle(packet.data(),packet.size(),true,false,output,0)); // retry
    }
    receiver.reset();
    // Corrupt/truncated/oversized inputs are rejected without out-of-bounds IO.
    for(size_t size=0;size<700;++size) {
        std::vector<uint8_t> input(size,0xa5);
        assert(!receiver.handle(input.data(),size,true,false,output,0));
    }
    demo::Header h{{'D','E','M','O'},demo::FILE_CHUNK,400,0,512,512};
    auto packet=frame(h,std::vector<uint8_t>(512,1));
    assert(receiver.handle(packet.data(),packet.size(),true,false,output,0));
    h.kind=demo::FILE_FINISH; h.offset=512; h.length=0;
    packet=frame(h,{});
    assert(receiver.handle(packet.data(),packet.size(),true,false,output,0));
    assert(receiver.handle(packet.data(),packet.size(),true,false,output,0)); // receipt retry
    receiver.reset();
}
int main() {
    lifecycle(); commands(); memoryReports(); pauseDiagnostics(); actualPauses(); demoMemory();
    puts("PASS: bridge cleanup, command bounds, memory reports, actual pause/queue functions, demo ownership");
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssh-header", type=Path, default=MAIN / "ssh_client.h")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="esp32-memory-tests-") as directory:
        root = Path(directory)
        (root / "test_platform.h").write_text(PLATFORM)
        wrappers = ["Arduino.h", "WiFi.h", "Client.h", "lwip/sockets.h",
                    "freertos/FreeRTOS.h", "freertos/task.h", "freertos/semphr.h",
                    "libssh/libssh.h", "libssh_esp32.h", "esp_heap_caps.h"]
        for name in wrappers:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#pragma once\n#include "test_platform.h"\n')
        (root / "secrets.h").write_text(
            '#pragma once\nconstexpr auto SSH_PRIVATE_KEY="test";\n'
            'constexpr auto SOC_USERNAME="test", SOC_PASSWORD="test";\n'
            'constexpr auto WIFI_SSID="test", WIFI_PASSWORD="test";\n')
        (root / "network_profile.h").write_bytes((MAIN / "network_profile.h").read_bytes())
        for name in ["debug_commands.h", "memory_debug.h", "debug_serial.h",
                     "demo_protocol.h", "telemetry_packet.h", "telemetry_debug.h", "transport_debug.h", "diagnostic_clock.h", "sampling_debug.h"]:
            (root / name).write_bytes((MAIN / name).read_bytes())
        # Transport state is real; TCP/RTOS hardware adapters are separately
        # exercised by network_diagnostics_test.py, not these lifecycle fakes.
        (root / "tcp_debug.h").write_text('#pragma once\nnamespace TcpDebug { inline void attach(int) {} inline void clear() {} }\n')
        (root / "rtos_debug.h").write_text('#pragma once\nnamespace RtosDebug { enum Role { Bridge }; inline void registerSelf(Role) {} inline void beat(Role) {} }\n')
        (root / "ssh_stage_debug.h").write_text("#pragma once\nnamespace SshStageDebug { inline void begin(unsigned,void*,uint32_t) {} inline void finish(unsigned,int) {} }\n")
        (root / "ssh_client.h").write_bytes(args.ssh_header.read_bytes())
        sketch = (MAIN / "main.ino").read_text()
        functions = []
        for signature in ("bool enqueueMotionSample(const sensors_event_t& a,",
                          "void runControlledPause() {"):
            start = sketch.rindex(signature) # Skip the sketch's forward declaration.
            opening = sketch.index("{", start)
            depth, end = 1, opening + 1
            # These two bodies contain no brace characters in string literals.
            while depth:
                depth += (sketch[end] == "{") - (sketch[end] == "}")
                end += 1
            functions.append(sketch[start:end])
        capacity = re.search(r"const uint8_t QUEUE_MAX_SIZE = (\d+);", sketch).group(1)
        code = TEST.replace("QUEUE_CAPACITY;", capacity + ";")
        code = code.replace("// ACTUAL_SKETCH_FUNCTIONS", "\n".join(functions))
        (root / "test.cpp").write_text(code)
        executable = root / "test"
        subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-I", str(root), str(root / "test.cpp"), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
