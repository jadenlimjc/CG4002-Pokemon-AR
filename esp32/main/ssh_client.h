#ifndef SSH_FORWARD_CLIENT_H
#define SSH_FORWARD_CLIENT_H

// ==========================================================
// Two-hop SSH forwarding client.
//
// The campus profile uses stujump and Ultra96. A local profile can point the
// same two real SSH sessions at the controllable mock lab.
//
// Topology:
//
//   ESP32 --session1(SSH)--> jump --channel1(direct-tcpip)--> target:22
//                                                                    |
//                                          (channel1 bytes are the transport
//                                           for a second SSH handshake, via
//                                           a local loopback socket pair)
//                                                                    |
//   ESP32 --session2(SSH, over the bridge)------------------------> target
//                                          --channel2(direct-tcpip)--> service
//
// session1/channel1 are created here, then handed off to a
// dedicated task that owns them exclusively for the rest of
// their life (no cross-task access to a single ssh_session).
// That task also owns the bridge's server-side socket.
//
// session2/channel2 are owned by this class and are what
// PubSubClient actually reads/writes through.
// ==========================================================

#include <Arduino.h>
#include <WiFi.h>
#include <Client.h>
#include <string.h>
#include <fcntl.h>
#include <lwip/sockets.h>

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>

#include <libssh/libssh.h>
#include "libssh_esp32.h"
#include "secrets.h"
#include "network_profile.h"

class SSHForwardClient : public Client {
private:
    static constexpr size_t BRIDGE_BUF_SIZE = 2048;
    static constexpr uint32_t SSH_WRITE_BUDGET_MS = 350;
    static constexpr uint32_t BRIDGE_STOP_WAIT_MS = 100;

    struct PumpTaskParams {
        ssh_session session1;
        ssh_channel channel1;
        int srv_sock;
        volatile bool *keep_running;
        SemaphoreHandle_t done_sem;
    };

    // Session1 / channel1 exist only long enough to be handed to the
    // pump task. After that this class never touches them again.
    ssh_session session1 = nullptr;
    ssh_channel jump_channel = nullptr;

    // Session2 / channel2 are what the MQTT client actually uses.
    ssh_session session2 = nullptr;
    ssh_channel channel2 = nullptr;

    int cli_sock = -1; // session2's transport fd (our end of the bridge)

    TaskHandle_t pump_task_handle = nullptr;
    volatile bool pump_keep_running = false;
    SemaphoreHandle_t pump_done_sem = nullptr;

    bool is_connected = false;

    static bool writeChannelWithinBudget(ssh_session session, ssh_channel channel,
                                         const uint8_t *buffer, size_t length,
                                         const volatile bool *keep_running = nullptr) {
        (void)session;
        const uint32_t started = millis();
        size_t written = 0;
        while (written < length && (!keep_running || *keep_running)) {
            const uint32_t remaining = static_cast<uint32_t>(length - written);
            const int rc = ssh_channel_write(channel, buffer + written, remaining);
            if (rc > 0) {
                written += static_cast<size_t>(rc);
                continue;
            }
            if (rc != SSH_AGAIN) return false;
            if (static_cast<uint32_t>(millis() - started) >= SSH_WRITE_BUDGET_MS) {
                Serial.printf("[SSH] write exceeded %lu ms; abandoning tunnel.\n",
                                   (unsigned long)SSH_WRITE_BUDGET_MS);
                return false;
            }
            vTaskDelay(pdMS_TO_TICKS(1));
        }
        return written == length;
    }

    void abandonTunnel() {
        is_connected = false;
        if (cli_sock >= 0) shutdown(cli_sock, SHUT_RDWR);
    }

    // ----------------------------------------------------------------
    // Public-key auth first then password. Same pattern as before,
    // parameterized so it works for both stujump and ultra96.
    // ----------------------------------------------------------------
    bool authenticate(ssh_session s, const char *user, const char *password) {
        ssh_key private_key = nullptr;

        int rc = ssh_pki_import_privkey_base64(SSH_PRIVATE_KEY, nullptr, nullptr, nullptr, &private_key);

        if (rc == SSH_OK && private_key) {
            rc = ssh_userauth_publickey(s, user, private_key);
            ssh_key_free(private_key);

            if (rc == SSH_AUTH_SUCCESS) {
                Serial.printf("[SSH] Pubkey auth OK for %s.\n", user);
                return true;
            }

            if (rc == SSH_AUTH_PARTIAL) {
                Serial.printf("[SSH] Pubkey accepted for %s, password also required.\n", user);
            } else {
                Serial.printf("[SSH] Pubkey auth failed for %s: %s\n", user, ssh_get_error(s));
            }
        } else {
            Serial.printf("[SSH] Private key import failed: %s\n", ssh_get_error(s));
        }

        rc = ssh_userauth_password(s, user, password);

        if (rc != SSH_AUTH_SUCCESS) {
            Serial.printf("[SSH] Password auth failed for %s: %s\n", user, ssh_get_error(s));
            return false;
        }

        Serial.printf("[SSH] Password auth OK for %s.\n", user);
        return true;
    }

    // ----------------------------------------------------------------
    // Build a connected local TCP socket pair over the loopback
    // interface. libssh needs a real socket fd for SSH_OPTIONS_FD;
    // it won't accept an ssh_channel directly.
    // ----------------------------------------------------------------
    static bool createLoopbackPair(int &srv_sock_out, int &cli_sock_out) {
        int listen_sock = socket(AF_INET, SOCK_STREAM, 0);
        if (listen_sock < 0) {
            Serial.println("[BRIDGE] listen socket() failed.");
            return false;
        }

        struct sockaddr_in addr;
        memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        addr.sin_port = 0; // ephemeral

        if (bind(listen_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
            Serial.println("[BRIDGE] bind() failed (loopback iface disabled in lwIP config?).");
            close(listen_sock);
            return false;
        }

        socklen_t addr_len = sizeof(addr);
        if (getsockname(listen_sock, (struct sockaddr *)&addr, &addr_len) < 0) {
            Serial.println("[BRIDGE] getsockname() failed.");
            close(listen_sock);
            return false;
        }

        if (listen(listen_sock, 1) < 0) {
            Serial.println("[BRIDGE] listen() failed.");
            close(listen_sock);
            return false;
        }

        int cli_sock = socket(AF_INET, SOCK_STREAM, 0);
        if (cli_sock < 0) {
            Serial.println("[BRIDGE] client socket() failed.");
            close(listen_sock);
            return false;
        }

        // Non-blocking connect so the accept() below isn't skipped
        // while the local TCP handshake is still in flight.
        int orig_flags = fcntl(cli_sock, F_GETFL, 0);
        fcntl(cli_sock, F_SETFL, orig_flags | O_NONBLOCK);

        ::connect(cli_sock, (struct sockaddr *)&addr, sizeof(addr));
        // EINPROGRESS expected here; the loopback handshake finishes
        // essentially immediately, so a short blocking accept is fine.

        struct sockaddr_in peer_addr;
        socklen_t peer_len = sizeof(peer_addr);

        int srv_sock = accept(listen_sock, (struct sockaddr *)&peer_addr, &peer_len);
        close(listen_sock);

        if (srv_sock < 0) {
            Serial.println("[BRIDGE] accept() failed.");
            close(cli_sock);
            return false;
        }

        fd_set wfds;
        FD_ZERO(&wfds);
        FD_SET(cli_sock, &wfds);
        struct timeval tv = { .tv_sec = 2, .tv_usec = 0 };

        int sel = select(cli_sock + 1, nullptr, &wfds, nullptr, &tv);
        if (sel <= 0) {
            Serial.println("[BRIDGE] client-side connect() did not complete.");
            close(cli_sock);
            close(srv_sock);
            return false;
        }

        int so_err = 0;
        socklen_t so_err_len = sizeof(so_err);
        getsockopt(cli_sock, SOL_SOCKET, SO_ERROR, &so_err, &so_err_len);

        if (so_err != 0) {
            Serial.printf("[BRIDGE] client-side connect() error: %d\n", so_err);
            close(cli_sock);
            close(srv_sock);
            return false;
        }

        // libssh expects a blocking fd.
        fcntl(cli_sock, F_SETFL, orig_flags);

        // Session2 uses SSH_OPTIONS_FD, which bypasses libssh's socket setup.
        // Disable Nagle on both bridge ends before either SSH task uses them.
        int no_delay = 1;
        if (setsockopt(cli_sock, IPPROTO_TCP, TCP_NODELAY, &no_delay, sizeof(no_delay)) < 0 ||
            setsockopt(srv_sock, IPPROTO_TCP, TCP_NODELAY, &no_delay, sizeof(no_delay)) < 0) {
            Serial.println("[BRIDGE] Failed to enable TCP_NODELAY.");
            close(cli_sock);
            close(srv_sock);
            return false;
        }

        srv_sock_out = srv_sock;
        cli_sock_out = cli_sock;
        return true;
    }

    // ----------------------------------------------------------------
    // Owns session1/jump_channel/srv_sock for their entire lifetime.
    // Shuttles bytes between the SSH channel to ultra96:22 and the
    // local socket that session2's handshake/IO reads and writes.
    // ----------------------------------------------------------------
    static void bridgePumpTask(void *pv) {
        PumpTaskParams *p = static_cast<PumpTaskParams *>(pv);
        uint8_t buf[BRIDGE_BUF_SIZE];

        Serial.println("[BRIDGE] Pump task started.");

        while (*p->keep_running) {
            // channel1 -> srv_sock
            int avail = ssh_channel_poll(p->channel1, 0);

            if (avail == SSH_ERROR || avail == SSH_EOF) {
                Serial.println("[BRIDGE] channel1 closed/error.");
                break;
            }

            bool broken = false;

            while (avail > 0) {
                int to_read = (avail > (int)sizeof(buf)) ? (int)sizeof(buf) : avail;
                int n = ssh_channel_read(p->channel1, buf, to_read, 0);

                if (n <= 0) {
                    broken = true;
                    break;
                }

                int sent = 0;
                while (sent < n) {
                    int s = send(p->srv_sock, buf + sent, n - sent, 0);
                    if (s <= 0) {
                        broken = true;
                        break;
                    }
                    sent += s;
                }

                if (broken) break;

                avail = ssh_channel_poll(p->channel1, 0);
                if (avail == SSH_ERROR || avail == SSH_EOF) {
                    broken = true;
                    break;
                }
            }

            if (broken) {
                Serial.println("[BRIDGE] channel1 -> srv_sock relay broke.");
                break;
            }

            // srv_sock -> channel1, 20 ms poll so the keep_running flag
            // is checked promptly on stop().
            fd_set readfds;
            FD_ZERO(&readfds);
            FD_SET(p->srv_sock, &readfds);

            struct timeval tv = { .tv_sec = 0, .tv_usec = 20000 };
            int sel = select(p->srv_sock + 1, &readfds, nullptr, nullptr, &tv);

            if (sel < 0) {
                Serial.println("[BRIDGE] select() error.");
                break;
            }

            if (sel > 0 && FD_ISSET(p->srv_sock, &readfds)) {
                int n = recv(p->srv_sock, buf, sizeof(buf), 0);

                if (n <= 0) {
                    Serial.println("[BRIDGE] srv_sock closed.");
                    break;
                }

                if (!writeChannelWithinBudget(p->session1, p->channel1, buf, n,
                                              p->keep_running)) {
                    Serial.println("[BRIDGE] srv_sock -> channel1 relay broke.");
                    break;
                }
            }
        }

        Serial.println("[BRIDGE] Pump task exiting, freeing session1.");

        close(p->srv_sock);
        ssh_channel_close(p->channel1);
        ssh_channel_free(p->channel1);
        ssh_disconnect(p->session1);
        ssh_free(p->session1);

        SemaphoreHandle_t done_sem = p->done_sem;
        delete p;

        xSemaphoreGive(done_sem);
        vTaskDelete(nullptr);
    }

public:
    SSHForwardClient() {
        pump_done_sem = xSemaphoreCreateBinary();
    }

    ~SSHForwardClient() {
        stop();
        if (pump_done_sem) {
            vSemaphoreDelete(pump_done_sem);
        }
    }

    int connect(IPAddress ip, uint16_t port) override {
        (void)ip;
        (void)port;
        return connect(NetworkProfile::SERVICE_HOST, NetworkProfile::SERVICE_PORT);
    }

    int connect(const char *host, uint16_t port) override {
        (void)host;
        (void)port;

        stop();

        // ================= Stage 1: ESP32 -> jump host =================

        Serial.printf("[SSH] Network profile: %s\n", NetworkProfile::NAME);
        Serial.printf("[SSH] Stage 1: connecting to jump host %s:%u.\n",
                      NetworkProfile::JUMP_HOST, NetworkProfile::JUMP_PORT);

        session1 = ssh_new();
        if (!session1) {
            Serial.println("[SSH] session1 alloc failed.");
            return 0;
        }

        unsigned int jump_port = NetworkProfile::JUMP_PORT;
        int process_config_off = 0;
        int no_delay = 1;

        if (ssh_options_set(session1, SSH_OPTIONS_HOST, NetworkProfile::JUMP_HOST) != SSH_OK ||
            ssh_options_set(session1, SSH_OPTIONS_PORT, &jump_port) != SSH_OK ||
            ssh_options_set(session1, SSH_OPTIONS_USER, NetworkProfile::JUMP_USERNAME) != SSH_OK ||
            ssh_options_set(session1, SSH_OPTIONS_NODELAY, &no_delay) != SSH_OK ||
            ssh_options_set(session1, SSH_OPTIONS_PROCESS_CONFIG, &process_config_off) != SSH_OK) {

            Serial.printf("[SSH] session1 options failed: %s\n", ssh_get_error(session1));
            stop();
            return 0;
        }

        if (ssh_connect(session1) != SSH_OK) {
            Serial.printf("[SSH] session1 connect failed: %s\n", ssh_get_error(session1));
            stop();
            return 0;
        }

        if (!authenticate(session1, NetworkProfile::JUMP_USERNAME, NetworkProfile::JUMP_PASSWORD)) {
            stop();
            return 0;
        }

        // direct-tcpip to the target SSH server, exactly what `ssh -J` uses.
        jump_channel = ssh_channel_new(session1);
        if (!jump_channel) {
            Serial.printf("[SSH] jump_channel alloc failed: %s\n", ssh_get_error(session1));
            stop();
            return 0;
        }

        if (ssh_channel_open_forward(jump_channel, NetworkProfile::TARGET_HOST, NetworkProfile::TARGET_SSH_PORT, "localhost", 0) != SSH_OK) {
            Serial.printf("[SSH] jump_channel open_forward failed: %s\n", ssh_get_error(session1));
            stop();
            return 0;
        }

        Serial.printf("[SSH] channel1 open (%s -> %s:%u).\n",
                      NetworkProfile::JUMP_HOST, NetworkProfile::TARGET_HOST,
                      NetworkProfile::TARGET_SSH_PORT);

        // ================= Bridge: local loopback pair =================

        int srv_sock = -1;

        if (!createLoopbackPair(srv_sock, cli_sock)) {
            Serial.println("[SSH] Bridge creation failed.");
            stop();
            return 0;
        }

        PumpTaskParams *pump_params = new PumpTaskParams();
        pump_params->session1 = session1;
        pump_params->channel1 = jump_channel;
        pump_params->srv_sock = srv_sock;
        pump_params->keep_running = &pump_keep_running;
        pump_params->done_sem = pump_done_sem;

        pump_keep_running = true;
        ssh_set_blocking(session1, 0);

        BaseType_t pump_result = xTaskCreate(bridgePumpTask, "SSHBridge", 8192, pump_params, 3, &pump_task_handle);

        if (pump_result != pdPASS) {
            Serial.println("[SSH] Bridge pump task creation failed.");

            delete pump_params;
            close(cli_sock);
            close(srv_sock);
            ssh_channel_close(jump_channel);
            ssh_channel_free(jump_channel);
            ssh_disconnect(session1);
            ssh_free(session1);

            jump_channel = nullptr;
            session1 = nullptr;
            cli_sock = -1;
            return 0;
        }

        // session1/jump_channel now belong exclusively to the pump task.
        session1 = nullptr;
        jump_channel = nullptr;

        // ================= Stage 2: ESP32 -> [bridge] -> target =================

        Serial.printf("[SSH] Stage 2: connecting to %s via jump host.\n",
                      NetworkProfile::TARGET_HOST);

        session2 = ssh_new();
        if (!session2) {
            Serial.println("[SSH] session2 alloc failed.");
            stop();
            return 0;
        }

        socket_t fd = static_cast<socket_t>(cli_sock);
        int process_config_off2 = 0;

        if (ssh_options_set(session2, SSH_OPTIONS_FD, &fd) != SSH_OK ||
            ssh_options_set(session2, SSH_OPTIONS_USER, NetworkProfile::TARGET_USERNAME) != SSH_OK ||
            ssh_options_set(session2, SSH_OPTIONS_PROCESS_CONFIG, &process_config_off2) != SSH_OK) {

            Serial.printf("[SSH] session2 options failed: %s\n", ssh_get_error(session2));
            stop();
            return 0;
        }

        if (ssh_connect(session2) != SSH_OK) {
            Serial.printf("[SSH] session2 connect failed: %s\n", ssh_get_error(session2));
            stop();
            return 0;
        }

        if (!authenticate(session2, NetworkProfile::TARGET_USERNAME, NetworkProfile::TARGET_PASSWORD)) {
            stop();
            return 0;
        }

        // ================= Forward: target -> configured service =================

        channel2 = ssh_channel_new(session2);
        if (!channel2) {
            Serial.printf("[SSH] channel2 alloc failed: %s\n", ssh_get_error(session2));
            stop();
            return 0;
        }

        if (ssh_channel_open_forward(channel2, NetworkProfile::SERVICE_HOST, NetworkProfile::SERVICE_PORT, "localhost", 0) != SSH_OK) {
            Serial.printf("[SSH] channel2 open_forward failed: %s\n", ssh_get_error(session2));
            stop();
            return 0;
        }

        ssh_set_blocking(session2, 0);

        is_connected = true;

        Serial.printf("[SSH] Tunnel established: ESP32 -> %s -> %s -> %s:%u\n",
                      NetworkProfile::JUMP_HOST, NetworkProfile::TARGET_HOST,
                      NetworkProfile::SERVICE_HOST, NetworkProfile::SERVICE_PORT);

        return 1;
    }

    size_t write(uint8_t b) override {
        return write(&b, 1);
    }

    size_t write(const uint8_t *buf, size_t size) override {
        if (!is_connected || !channel2) {
            return 0;
        }

        if (writeChannelWithinBudget(session2, channel2, buf, size)) {
            return size;
        }
        abandonTunnel();
        return 0;
    }

    int available() override {
        if (!is_connected || !channel2) {
            return 0;
        }

        int rc = ssh_channel_poll(channel2, 0);

        if (rc <= 0) {
            return 0;
        }

        return rc;
    }

    int read() override {
        uint8_t b;
        if (read(&b, 1) == 1) {
            return b;
        }
        return -1;
    }

    int read(uint8_t *buf, size_t size) override {
        if (!is_connected || !channel2) {
            return 0;
        }

        int rc = ssh_channel_read(channel2, buf, static_cast<uint32_t>(size), 0);
        if (rc == SSH_AGAIN || rc < 0) {
            return 0;
        }
        return rc;
    }

    int peek() override {
        return -1;
    }

    void flush() override {}

    void stop() override {
        is_connected = false;

        // ---- Session2 is owned by this thread. ----
        if (channel2) {
            ssh_channel_close(channel2);
            ssh_channel_free(channel2);
            channel2 = nullptr;
        }

        if (session2) {
            ssh_disconnect(session2);
            ssh_free(session2);
            session2 = nullptr;
        }

        if (cli_sock >= 0) {
            close(cli_sock);
            cli_sock = -1;
        }

        // ---- Session1/jump_channel/srv_sock are owned by the pump task. ----
        if (pump_task_handle) {
            pump_keep_running = false;
            const bool stopped = xSemaphoreTake(pump_done_sem, pdMS_TO_TICKS(BRIDGE_STOP_WAIT_MS)) == pdTRUE;
            if (stopped) {
                pump_task_handle = nullptr;
            } else {
                // Preserve ownership and keep the stop flag false. connect()
                // must not spawn another pump or revive this one on timeout.
                Serial.println("[SSH] Bridge cleanup pending; resources retained until exit.");
            }
        }

        // Only reached if connect() failed before the pump task started;
        // otherwise these are already null.
        if (jump_channel) {
            ssh_channel_close(jump_channel);
            ssh_channel_free(jump_channel);
            jump_channel = nullptr;
        }

        if (session1) {
            ssh_disconnect(session1);
            ssh_free(session1);
            session1 = nullptr;
        }
    }

    uint8_t connected() override {
        if (!is_connected || !session2 || !channel2) {
            return 0;
        }

        return ssh_is_connected(session2) && ssh_channel_is_open(channel2);
    }

    operator bool() override {
        return connected();
    }
};

#endif
