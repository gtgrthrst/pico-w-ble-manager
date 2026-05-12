import bluetooth
import machine
import time
import network
import json
import os
from micropython import const
from ble_advertising import advertising_payload

# 硬體設定
led = machine.Pin("LED", machine.Pin.OUT)

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_NOTIFY,)
_UART_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), 0x08 | 0x04,)
_UART_SERVICE = (_UART_UUID, (_UART_TX, _UART_RX),)

class DeviceManager:
    def __init__(self, ble):
        self._ble = ble
        self._ble.active(True)
        self._ble.irq(self._irq)
        ((self._handle_tx, self._handle_rx),) = self._ble.gatts_register_services((_UART_SERVICE,))
        self._connections = set()
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        
        self.cmd_buffer = "" # 指令緩衝區
        self.load_and_connect()
        self._advertise()

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._connections.add(data[0])
            print("[BLE] 已連線")
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._connections.remove(data[0])
            print("[BLE] 已斷開")
            self._advertise()
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if value_handle == self._handle_rx:
                msg = self._ble.gatts_read(self._handle_rx).decode().strip()
                self.handle_chunk(msg)

    def handle_chunk(self, chunk):
        # 收到結束符號
        if chunk == "END":
            print(f"[系統] 收到完整指令: {self.cmd_buffer}")
            self.process_final_command(self.cmd_buffer)
            self.cmd_buffer = "" # 處理完清空
        else:
            self.cmd_buffer += chunk
            print(f"[系統] 緩衝中: {self.cmd_buffer}")

    def process_final_command(self, cmd):
        if cmd == "SCAN":
            self.scan_wifi()
        elif cmd.startswith("W:"):
            try:
                ssid, pw = cmd[2:].split(",")
                self.save_config(ssid, pw)
                self.connect_wifi(ssid, pw)
            except:
                self.send_notify("ERR:Format Error")
        elif cmd == "1": led.value(1)
        elif cmd == "0": led.value(0)

    def send_notify(self, text):
        for conn in self._connections:
            self._ble.gatts_notify(conn, self._handle_tx, text)

    def scan_wifi(self):
        self.send_notify("MSG:Scanning...")
        res = self.wlan.scan()
        # 排序並取前 5 個
        ssids = sorted(res, key=lambda x: x[3], reverse=True)
        names = [s[0].decode('utf-8') for s in ssids if s[0]][:5]
        self.send_notify("SSIDS:" + ",".join(names))

    def connect_wifi(self, ssid, pw):
        self.send_notify("MSG:Connecting...")
        self.wlan.disconnect()
        self.wlan.connect(ssid, pw)
        
        attempt = 0
        while not self.wlan.isconnected() and attempt < 15:
            time.sleep(1)
            attempt += 1
            print(f"連線嘗試 {attempt}...")
            
        if self.wlan.isconnected():
            ip = self.wlan.ifconfig()[0]
            print(f"✅ 連線成功: {ip}")
            self.send_notify(f"SUCCESS:{ip}")
        else:
            print("❌ 連線超時")
            self.send_notify("ERR:Timeout")

    def save_config(self, s, p):
        with open('config.json', 'w') as f:
            json.dump({'ssid': s, 'pw': p}, f)

    def load_and_connect(self):
        if 'config.json' in os.listdir():
            try:
                with open('config.json', 'r') as f:
                    c = json.load(f)
                    self.wlan.connect(c['ssid'], c['pw'])
            except: pass

    def _advertise(self, interval_us=500000):
        p = advertising_payload(name="PicoW", services=[_UART_UUID])
        self._ble.gap_advertise(interval_us, adv_data=p)

ble = bluetooth.BLE()
DeviceManager(ble)
