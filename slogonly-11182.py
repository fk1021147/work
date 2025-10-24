#######################################################
#import
#######################################################
import os
import sys
import threading
import datetime
import time
import queue
import random
import subprocess
import configparser
import shutil
import json
import tkinter as tk
from tkinter import scrolledtext
from tkinter import ttk
from tkinter import messagebox

import serial
import serial.tools.list_ports
import cv2
import requests

#######################################################
#User Setting
#######################################################
#初期設定として使用
UCOM_COM_PORT = "COM4"
QNX_COM_PORT = "COM16"
SAIL_COM_PORT = "COM20"
ANDROID_COM_PORT = "COM21"
PIKA_COM_PORT = "COM8"

# "ISP = 0" or "ICB = 1"
TOOL_MODE = 1

# "Dump Off = 0" or "MiniDump On = 1" or "FullDump ON = 2"
DUMP_MODE = 0

# "テスト用のコマンド送信画面 非表示=0 表示=1"
DEBUG_MODE = 1

# "Normal Sail log = 0" or "Additional Sail log = 1"
ADD_SAILLOG_ON = 0

# "SAIL Debug mode ENABLE = 0" or "SAIL Debug mode DISABLE = 1"
SAIL_DEBUG_MODE_DISABLE = 0

# "何もしない = 0" "suspend errror時にコマンドを送信し、Sleepチェックを行う= 1"
SLEEP_CHECK = 0

# "通常のサスレジ = 0" or "ACCOFF-ON(サスペンド)折り返し(ポイント指定) = 1" or
# "ACCOFF-ON(サスペンド)折り返し(固定時間)= 2" or "ACCOFF-ON(サスペンド)折り返し(ランダム時間:1-100秒)= 3" or
# "ACCON-OFF(レジューム)折り返し(ポイント指定)=4" or "ACCON-OFF(レジューム)折り返し(固定時間)=5" or
# "ACCON-OFF(レジューム)折り返し(ランダム時間:1-100秒)=6"
TEST_MODE = 0

#ACCOFF-ON折り返し固定時間(sec)
ACC_OFFON_TIME = 90

#ACCOFF-ON折り返しランダム時間範囲min-max(sec)
ACC_OFFON_RANDUM_MIN = 1
ACC_OFFON_RANDUM_MAX = 100

# "動作なし= 0" or "resume時のadbのscreenshotを取得"=1
ADB_SS_ENABLE = 0

# "動作なし= 0" or "#SAILの特定ログが検出されない状態で、'PMT:ASEE T.O'を検知した場合はテストを停止"=1
ASEE_TO_TESTSTOP = 0

# "動作なし= 0" or "Androidコンソール上のlogcat有効 = 1"
ANDROID_LOGCAT_ENABLE = 0

# "カメラ有効:1(True)/無効:0(False)"
CAMERA_ENABLE = 0
# 接続するカメラのID
# 事前にcamera_id_search.pyを実行し、接続可能なカメラIDを確認してください
CAMERA_ID = 0

# 解像度設定
CAMERA_FRAME_WIDTH = 1280
CAMERA_FRAME_HEIGHT = 720

# "Teamsへの自動通知 有効:1(True)/無効:0(False)"
TEAMS_ENABLE = 0
TEAMS_TITLE = 'サスレジ試験:齊藤席'
TEAMS_URL = ''

#0=無効、1=設定用のwindowでテスト環境設定を行う
TOOL_EXE_GENMODE = 1
#######################################################
#Constant Definition
#######################################################
TOOL_STATE_RUN = 0
TOOL_STATE_END = 1
TOOL_STATE_ERROR = 2

RESULT_OK = 0
RESULT_NG = 1
RESULT_TO = 2

TASK_INIT = 0
TASK_SUPEND = 1
TASK_SUPEND_WAIT = 2
TASK_RESUME = 3
TASK_RESUME_WAIT = 4
TASK_ERROR = 5
TASK_RUMDUMP_WAIT = 6
TASK_STOP = 7
TASK_NONE = 8

COUNTLOG_WRITE_INIT = 0
COUNTLOG_WRITE = 1
TESTLOG_WRITE_INIT = 2
TESTLOG_WRITE = 3
TESTLOG_SUS_ERROR = 4
TESTLOG_RES_ERROR = 5
TESTLOG_RESET_SUS_ERROR = 6
TESTLOG_RESET_RES_ERROR = 7
TESTLOG_CHG = 8
TESTLOG_END = 9

TESTLOG_MAX_COUNT = 1000

SERIAL_READ = 0
SERIAL_WRITE = 1

EV_UCOM_SER_WRITE = 0

EV_QNX_SER_WRITE = 0

EV_ANDROID_SER_WRITE = 0

EV_SAIL_SER_WRITE = 0

EV_CAMERA_SS_SUSPEND = 0
EV_CAMERA_SS_RESUME = 1
EV_CAMERA_SS_SUS_ERR = 2
EV_CAMERA_SS_RES_ERR = 3


#######################################################
#global Variable Definition
#######################################################
tool_state = TOOL_STATE_RUN

suspend_wait_flag = 0
resume_wait_flag = 0

suspend_count = 0
resume_count = 0
supend_error_count = 0
resume_error_count = 0
consecutive_success_count = 0
consecutive_success_max_count = 0

log_index = 0
test_task = TASK_INIT
test_task_copy = TASK_NONE

lock1 = threading.Lock()
lock2 = threading.Lock()
lock3 = threading.Lock()
lock4 = threading.Lock()
lock5 = threading.Lock()

ucom_console_list =[]
qnx_console_list =[]
android_console_list =[]
sail_console_list =[]

q_ucom = queue.Queue()
q_qnx = queue.Queue()
q_android = queue.Queue()
q_sail = queue.Queue()
q_camera = queue.Queue()

ramdump_timeoutcnt = 0

ucom_failsafe_list = [
        # [0:フェールセーフ種別, 1:フェールセーフ発生時ログ]
        ['SoC動作開始の監視', 'I:1:PMT:INIT_STATUS Giveup'   ],
        ['Host RPC疎通開始の監視', 'M70_M10MS_STEP,68'       ],
        ['Android VM動作開始の監視', 'I:1:PMT:GUESTVM giveup'],
        ['Guest RPC疎通開始の監視', 'I:1:PMT:GUESTRpc giveup'],
        #['ACC/IG On時のNormal Running受信監視', 'XXXXX'],
        ['Android VMオフ監視', 'I:1:PMT:270sTO'],
        ['サスペンド状態端子の監視', 'I:1:PMT:ASEE T.O.'],
        ['QNX終了監視', 'I:1:PMT:13MinOver'],
        ['SoC Reset監視', 'SoCRst_P11'],
        ['サスペンド処理中のSoC Reset監視', 'SoCRst_P24'],
        ['PMIC故障監視', 'PSAIL_ERR_P11'],
        ['PMIC故障監視', 'PSAIL_ERR_P21'],
        ['Host RPC Heartbeat監視', 'M70_M10MS_STEP,68'],
        ['Guest RPC Heartbeat監視', 'GetHBErr'],
        ['uCom内のWatchDog監視', 'D:2:VHM:RF.'],
        ['ユーザー操作によるAndroid VM再起動コマンドの監視(ステリモ多重押し)', 'I:1:PMT:HdKeyType:0'],
        ['ユーザー操作によるAndroid VM再起動コマンドの監視(MCU_DEBUG)', 'I:1:PMT:DbgCmd:30,30'],
        #['MAIN3.3V異常検出', 'MAIN_3_3V_PF=0'],
        ['MAIN1.8V異常検出', 'Main1_8VErr,1'],
        ['MAIN1.8V異常検出', 'Main1_8VErr,2'],
        #['MAIN1.2V異常検出', 'MAIN_1_2V_PF=0'],
        ['MAIN(1.2V or 1.8V or 3.3V)異常検出', 'PwrMonErr'],
        ['Android VM異常監視', 'I:1:PMT:Det GUEST_STS Lo'],
        ['QNX System Failure Monitor監視','M70_M10MS_STEP,68'],
    ]
    
    
suspend_select_trigger = 9
suspend_trigger_list = [
    
        #[0:トリガーログの出力先、1:トリガーとなるログ,2:成功判定ログの出力先,3:成功判定のログ,4:画像を保存する際の略称,5:折り返し対象として扱う判定(True=対象、False=対象外)]
#        ['ucom'   ,'VHM:ACCOff'                                        ,'ucom'   ,'VHM:APSROn', 'ACCOff'          , False ],
#        ['ucom'   ,'VHM:IG1Off'                                        ,'ucom'   ,'VHM:APSROn', 'IG1Off'          , False ],
        ['ucom'   ,'VHM:DSEn'                                          ,'ucom'   ,'VHM:APSROn', 'DSEn'            , True ],
        ['ucom'   ,'VHM:SspFin'                                        ,'ucom'   ,'VHM:APSROn', 'SspFin'          , True ],
        ['qnx'    ,'[vmm][check_gvm_power_state] POWER_STATE_OFF'      ,'ucom'   ,'VHM:APSROn', 'POWER_STATE_OFF' , True ],
        ['ucom'   ,'PMT:GUEST_STS=0'                                   ,'ucom'   ,'VHM:APSROn', 'GUEST_STS_0'     , True ], # PMT:Det GUEST_STS Loが見つからないため、PMT:GUEST_STS=0
        ['ucom'   ,'PMT:GUEST_EN Low'                                  ,'ucom'   ,'VHM:APSROn', 'GUEST_EN_Low'    , True ], # PMT:Det GUEST_EN Lowが見つからないため、PMT:GUEST_EN Low
        ['ucom'   ,'PMT:Meter Fin End'                                 ,'ucom'   ,'VHM:APSROn', 'Meter_Fin_End'   , True ],
        ['qnx'    ,'OemPm I COemPmDataRpc SetRpcData shutdown_type_: 2','ucom'   ,'VHM:APSROn', 'shutdown_type_2' , True ],
        ['ucom'   ,'PMT:ASEE High'                                     ,'ucom'   ,'VHM:APSROn', 'ASEE_High'       , True ],
    ]
suspend_select_trigger = len(suspend_trigger_list) - 1

resume_trigger_list = [
        #[0:トリガーログの出力先、1:トリガーとなるログ,2:成功判定ログの出力先,3:成功判定のログ,4:画像を保存する際の略称,5:折り返し対象として扱う判定(True=対象、False=対象外)]
#        ['ucom','VHM:ACCOn','ucom','PMT:ASEE High','VHM_ACCOn',False ],
#        ['ucom','VHM:IG1On','ucom','PMT:ASEE High','VHM_IG1On',False ],
#        ['ucom','PMT:STR_WAKE High','ucom','PMT:ASEE High','STR_WAKE_High',False ],
#        ['ucom','PMT:INIT_STATUS High','ucom','PMT:ASEE High','INIT_STATUS_High',False ],
#        ['ucom','PMT:GUEST_EN High','ucom','PMT:ASEE High','GUEST_EN_High',False ],
        ['qnx','OemPm I [KPI]str_ctrl() devctl(STR) result: 0','ucom','PMT_ASEE High','str_ctrl()_result0',True ],
        ['qnx','[vmm INFO]send powerkey to done','ucom','PMT:ASEE High','send_powerkey_to_done',True ],
        ['qnx','SYS_MAIN:stat_change STARTUP to RUN','ucom','PMT:ASEE High','SYS_MAIN_stat_change',True ],
#        ['ucom','PMT:Host Rpc Conn','ucom','PMT:ASEE High','Host_Rpc_Conn',False ],
        ['qnx','[vmm][check_gvm_power_state] POWER_STATE_ON','ucom','PMT:ASEE High','POWER_STATE_ON',True ],
#        ['ucom','PMT:Det GUEST_STS Hi','ucom','PMT:ASEE High','Det_GUEST_STS_Hi',False ],
#        ['ucom','RPC:CommuSts[0]->[1]','ucom','PMT:ASEE High','CommuSts[0]→[1]',False ],
#        ['ucom','VHM:DSEx','ucom','PMT:ASEE High','VHM:DSEx',False ],
        ['ucom','VHM:APSROn','ucom','PMT:ASEE High','APSROn',True ],
    ]
resume_select_trigger = len(resume_trigger_list) - 1
    
#前回のレジュームの要因を記録[0]=Log or time ,[1]=画像を保存する際の略称
resume_after_trigger = ['','']

suspend_time = ACC_OFFON_TIME
resume_time = ACC_OFFON_TIME
sleep_chk_flg = 0

sail_Interrupt_check1 = 0
sail_Interrupt_check2 = 0

log_max_count = TESTLOG_MAX_COUNT
test_stop_flag = False

build_number = '-'
system_ucom = '-'
sail_img_id = '-'
fcp = '-'
hw_vari = '-'
wk_ev = '-'

#######################################################
#main
#######################################################

def main():
    global configpath
    global logfpath
    global ser_ucom
    global ser_qnx
    global ser_android
    global ser_sail
    
    # ファイルパスの設定
    currentpath = os.path.dirname(sys.argv[0])
    os.chdir(currentpath)
    configpath = fr'{currentpath}/config.ini'

    if TOOL_EXE_GENMODE == True:
        # iniファイルの生成
        ini_file_init()
        # 各種ポート設定
        gui_portsetting()

        with open('config.ini', 'w',encoding='shift_jis') as configfile:
            config.write(configfile)
    
    # 電源状態初期化
    pika_init()
    
    # ログフォルダの作成
    logfpath = currentpath + "/" "log" + "/" + datastr_get()
    os.makedirs(currentpath + "/" + "log", exist_ok=True)
    os.makedirs(logfpath, exist_ok=True)

    def click_close():
        global tool_state
        tool_state = TOOL_STATE_END
        masterwin.destroy()
    
    def test_count_cycle():
        if tool_state == TOOL_STATE_END:
            click_close()
        elif tool_state == TOOL_STATE_RUN:
            susres_counter.set('Suspend:' + str(suspend_count) + ' / Resume:'  + str(resume_count))
            sus_err_counter.set('Suspend Error:' + str(supend_error_count))
            res_err_counter.set('Resume Error:' + str(resume_error_count))
            con_counter.set('consecutive success:' + str(consecutive_success_count))
            con_max_counter.set('consecutive success max:' + str(consecutive_success_max_count))
            masterwin.update()
            masterwin.after(1000, test_count_cycle)
    
    def ucom_cyclechcek():
        global ucom_console_list
        datalist = []
    
        lock1.acquire()
        datalist.extend(ucom_console_list)
        ucom_console_list = []
        lock1.release()
        
        for data in datalist:
           ucom_logwin.insert(tk.END,data)
           ucom_logwin.insert(tk.END,'\n')
           ucom_logwin.pack(fill=tk.BOTH, expand=1)
           ucom_logwin.see(tk.END)
        ucom_lines = int(ucom_logwin.index('end-1c').split('.')[0])
        if ucom_lines > 1000:
            ucom_logwin.delete("1.0","2.0")
        masterwin.after(10, ucom_cyclechcek)
    
    def qnx_cyclechcek():
        global qnx_console_list
        datalist = []
    
        lock2.acquire()
        datalist.extend(qnx_console_list)
        qnx_console_list = []
        lock2.release()
        
        for data in datalist:
           qnx_logwin.insert(tk.END,data)
           qnx_logwin.insert(tk.END,'\n')
           qnx_logwin.pack(fill=tk.BOTH, expand=1)
           qnx_logwin.see(tk.END)
        qnx_lines = int(qnx_logwin.index('end-1c').split('.')[0])
        if qnx_lines > 1000:
            qnx_logwin.delete("1.0","2.0")
        masterwin.after(10, qnx_cyclechcek)

    def sail_cyclechcek():
        global sail_console_list
        datalist = []
    
        lock4.acquire()
        datalist.extend(sail_console_list)
        sail_console_list = []
        lock4.release()
        
        for data in datalist:
           sail_logwin.insert(tk.END,data)
           sail_logwin.insert(tk.END,'\n')
           sail_logwin.pack(fill=tk.BOTH, expand=1)
           sail_logwin.see(tk.END)
        sail_lines = int(sail_logwin.index('end-1c').split('.')[0])
        if sail_lines > 1000:
            sail_logwin.delete("1.0","2.0")
        masterwin.after(10, sail_cyclechcek)

    def android_cyclechcek():
        global android_console_list
        datalist = []
    
        lock3.acquire()
        datalist.extend(android_console_list)
        android_console_list = []
        lock3.release()
        
        for data in datalist:
           android_logwin.insert(tk.END,data)
           android_logwin.insert(tk.END,'\n')
           android_logwin.pack(fill=tk.BOTH, expand=1)
           android_logwin.see(tk.END)
        android_lines = int(android_logwin.index('end-1c').split('.')[0])
        if android_lines > 1000:
            android_logwin.delete("1.0","2.0")
        masterwin.after(10, android_cyclechcek)
    
    #マスターウインドウの設定
    masterwin = tk.Tk()
    masterwin.title ('test Count')
    masterwin.geometry("200x150+1210+0")
    masterwin.protocol("WM_DELETE_WINDOW", click_close)
    susres_counter = tk.StringVar()
    susres_counter.set('Suspend:' + str(suspend_count) + ' / Resume:'  + str(resume_count))
    countlabel1 = tk.Label(masterwin, textvariable=susres_counter)
    countlabel1.pack()
    
    sus_err_counter = tk.StringVar()
    sus_err_counter.set('Suspend Error:' + str(supend_error_count))
    countlabel2 = tk.Label(masterwin, textvariable=sus_err_counter)
    countlabel2.pack()
    
    
    res_err_counter = tk.StringVar()
    res_err_counter.set('Resume Error:' + str(resume_error_count))
    countlabel3 = tk.Label(masterwin, textvariable=res_err_counter)
    countlabel3.pack()

    
    con_counter = tk.StringVar()
    con_counter.set('consecutive success:' + str(consecutive_success_count))
    countlabel4 = tk.Label(masterwin, textvariable=con_counter)
    countlabel4.pack()
    
    con_max_counter = tk.StringVar()
    con_max_counter.set('consecutive success max:' + str(consecutive_success_max_count))
    countlabel5 = tk.Label(masterwin, textvariable=con_max_counter)
    countlabel5.pack()
    
    end_btn_text = tk.StringVar()
    end_btn_text.set('次のサイクルでテスト終了')
    
    def func_end_btn():
        global test_stop_flag
        test_stop_flag = True
        end_btn_text.set('テスト終了中')
        end_btn["state"] = tk.DISABLED
        
    end_btn = tk.Button(masterwin, textvariable=end_btn_text, command=func_end_btn)
    end_btn.pack()
    
    #任意のタイミングで入力したコマンド送信を行う
    if DEBUG_MODE == 1:
        debug_win = tk.Toplevel(masterwin)
        debug_win.title("コンソールへのコマンド送信")
        debug_win.geometry("400x150+1210+200")
        debug_win.protocol("WM_DELETE_WINDOW", click_close)
        
        debug_win.columnconfigure(2, weight=2)
        #ucom
        debug_label_ucom = tk.Label(debug_win, text=f'uCOM :{UCOM_COM_PORT}')
        debug_txbox_ucom = tk.Entry(debug_win, width=40)
        def func_debugbtn_ucom():
            senddata = debug_txbox_ucom.get()
            q_ucom.put((EV_UCOM_SER_WRITE, senddata))
            
        debug_btn_ucom = tk.Button(debug_win, text='送信', command=func_debugbtn_ucom)
        debug_label_ucom.grid(column=0,row=1)
        debug_txbox_ucom.grid(column=1,row=1)
        debug_btn_ucom.grid(column=2,row=1)
        
        #qnx
        debug_label_qnx = tk.Label(debug_win, text=f'QNX :{QNX_COM_PORT}')
        debug_txbox_qnx = tk.Entry(debug_win, width=40)
        def func_debugbtn_qnx():
            senddata = debug_txbox_qnx.get()
            q_qnx.put((EV_QNX_SER_WRITE, senddata))
            
        debug_btn_qnx = tk.Button(debug_win, text='送信', command=func_debugbtn_qnx)
        debug_label_qnx.grid(column=0,row=2)
        debug_txbox_qnx.grid(column=1,row=2)
        debug_btn_qnx.grid(column=2,row=2)
        
        #android
        debug_label_android = tk.Label(debug_win, text=f'android :{ANDROID_COM_PORT}')
        debug_txbox_android = tk.Entry(debug_win, width=40)
        def func_debugbtn_android():
            senddata = debug_txbox_android.get()
            q_android.put((EV_ANDROID_SER_WRITE, senddata))
            
        debug_btn_android = tk.Button(debug_win, text='送信', command=func_debugbtn_android)
        debug_label_android.grid(column=0,row=3)
        debug_txbox_android.grid(column=1,row=3)
        debug_btn_android.grid(column=2,row=3)

        #sail
        debug_label_sail = tk.Label(debug_win, text=f'sail :{SAIL_COM_PORT}')
        debug_txbox_sail = tk.Entry(debug_win, width=40)
        def func_debugbtn_sail():
            senddata = debug_txbox_sail.get()
            q_sail.put((EV_SAIL_SER_WRITE, senddata))
            
        debug_btn_sail = tk.Button(debug_win, text='送信', command=func_debugbtn_sail)
        debug_label_sail.grid(column=0,row=4)
        debug_txbox_sail.grid(column=1,row=4)
        debug_btn_sail.grid(column=2,row=4)


    #子ウインドウの設定
    #uCom表示用
    ucom_win = tk.Toplevel(masterwin)
    ucom_win.title("uCOM :" + UCOM_COM_PORT)
    ucom_win.geometry("600x400+0+0")
    ucom_win.protocol("WM_DELETE_WINDOW", click_close)
    ucom_logwin = scrolledtext.ScrolledText(ucom_win, bg="black", fg="white", cursor='arrow', wrap=tk.WORD, font=('Helvetica', '12'))
    ucom_logwin.pack(fill=tk.BOTH, expand=1)
    
    #qnx表示用    
    qnx_win = tk.Toplevel(masterwin)
    qnx_win.title("QNX:" + QNX_COM_PORT)
    qnx_win.geometry("600x400+601+0")
    qnx_win.protocol("WM_DELETE_WINDOW", click_close)
    qnx_logwin = scrolledtext.ScrolledText(qnx_win, bg="black", fg="white", cursor='arrow', wrap=tk.WORD, font=('Helvetica', '12'))
    qnx_logwin.pack(fill=tk.BOTH, expand=1)

    #sail表示用
    sail_win = tk.Toplevel(masterwin)
    sail_win.title("SAIL:" + SAIL_COM_PORT)
    sail_win.geometry("600x400+601+450")
    sail_win.protocol("WM_DELETE_WINDOW", click_close)
    sail_logwin = scrolledtext.ScrolledText(sail_win, bg="black", fg="white", cursor='arrow', wrap=tk.WORD, font=('Helvetica', '12'))
    sail_logwin.pack(fill=tk.BOTH, expand=1)

    #android表示用
    android_win = tk.Toplevel(masterwin)
    android_win.title("android:" + ANDROID_COM_PORT)
    android_win.geometry("600x400+0+450")
    android_win.protocol("WM_DELETE_WINDOW", click_close)
    android_logwin = scrolledtext.ScrolledText(android_win, bg="black", fg="white", cursor='arrow', wrap=tk.WORD, font=('Helvetica', '12'))
    android_logwin.pack(fill=tk.BOTH, expand=1)


    masterwin.after(500, test_count_cycle)
    masterwin.after(600, ucom_cyclechcek)
    masterwin.after(700, qnx_cyclechcek)
    masterwin.after(800, sail_cyclechcek)
    masterwin.after(900, android_cyclechcek)
    
    # スレッドの作成
    thread_ucom = threading.Thread(target=ucom_serial_communication, daemon=True)
    thread_qnx = threading.Thread(target=qnx_serial_communication, daemon=True)
    thread_sail = threading.Thread(target=android_serial_communication, daemon=True)
    thread_android = threading.Thread(target=sail_serial_communication, daemon=True)
    thread_susres_test = threading.Thread(target=func_susres_test, daemon=True)
    if CAMERA_ENABLE == True:
        thread_canera = threading.Thread(target=camera_control, daemon=True)
    
    thread_ucom.start()
    thread_qnx.start()
    thread_sail.start()
    thread_android.start()
    thread_susres_test.start()
    if CAMERA_ENABLE == True:
        thread_canera.start()
    
    masterwin.mainloop()
    time.sleep(1)
    susres_test_info(into_info='試験終了')
    
#######################################################
#Function
#######################################################
def ini_file_init():
    global UCOM_COM_PORT
    global QNX_COM_PORT
    global SAIL_COM_PORT
    global ANDROID_COM_PORT
    global PIKA_COM_PORT
    global TOOL_MODE
    global DUMP_MODE
    global DEBUG_MODE
    global ADD_SAILLOG_ON
    global SAIL_DEBUG_MODE_DISABLE
    global SLEEP_CHECK
    global TEST_MODE
    global ACC_OFFON_TIME
    global ACC_OFFON_RANDUM_MIN
    global ACC_OFFON_RANDUM_MAX
    global ADB_SS_ENABLE
    global ASEE_TO_TESTSTOP
    global CAMERA_ENABLE
    global CAMERA_ID
    global CAMERA_FRAME_WIDTH
    global CAMERA_FRAME_HEIGHT
    global TEAMS_ENABLE
    global TEAMS_URL
    global TEAMS_TITLE
    global suspend_trigger_list
    global config

    # INIファイルから設定取得/INIファイルがない場合は生成
    config = configparser.ConfigParser(interpolation=None)
    if (os.path.isfile(configpath)):
        try:
            config.read(configpath)
            UCOM_COM_PORT = config["BASE"]["ucom_com"]
            QNX_COM_PORT = config["BASE"]["qnx_com"]
            SAIL_COM_PORT = config["BASE"]["sail_com"]
            ANDROID_COM_PORT =config["BASE"]["android_com"]
            PIKA_COM_PORT = config["BASE"]["pika_com"]
            TOOL_MODE = int(config["BASE"]["tool_mode"])
            DUMP_MODE = int(config["BASE"]["dump_mode"])
            DEBUG_MODE = int(config["BASE"]["debug_mode"])
            ADD_SAILLOG_ON = int(config["BASE"]["add_sail_log"])
            SAIL_DEBUG_MODE_DISABLE = int(config["BASE"]["sail_debug_disable"])
            SLEEP_CHECK = int(config["BASE"]["sleep_check"])
            TEST_MODE = int(config["BASE"]["test_mode"])
            ACC_OFFON_TIME = int(config["BASE"]["acc_offon_time"])
            ACC_OFFON_RANDUM_MIN = int(config["BASE"]["acc_offon_randum_min"])
            ACC_OFFON_RANDUM_MAX = int(config["BASE"]["acc_offon_randum_max"])
            ADB_SS_ENABLE = int(config["BASE"]["adb_ss_enable"]) 
            ASEE_TO_TESTSTOP = int(config["BASE"]["asee_to_teststop"])
            CAMERA_ENABLE = int(config["BASE"]["camera_enable"])
            CAMERA_ID = int(config["BASE"]["camera_id"])
            CAMERA_FRAME_WIDTH = int(config["BASE"]["camera_frame_w"])
            CAMERA_FRAME_HEIGHT = int(config["BASE"]["camera_frame_h"])
            TEAMS_ENABLE = int(config["BASE"]["teams_enable"])
            TEAMS_URL = config["BASE"]["teams_url"]
            TEAMS_TITLE = config["BASE"]["teams_title"]
        except KeyError as e:
            config['BASE'] = {
                'ucom_com': UCOM_COM_PORT,
                'qnx_com': QNX_COM_PORT,
                'sail_com': SAIL_COM_PORT,
                'android_com': ANDROID_COM_PORT,
                'pika_com': PIKA_COM_PORT,
                'tool_mode': TOOL_MODE,
                'dump_mode': DUMP_MODE,
                'debug_mode': DEBUG_MODE,
                'add_sail_log': ADD_SAILLOG_ON,
                'sail_debug_disable': SAIL_DEBUG_MODE_DISABLE,
                'sleep_check': SLEEP_CHECK,
                'test_mode' : TEST_MODE,
                'acc_offon_time' : ACC_OFFON_TIME,
                'acc_offon_randum_min' : ACC_OFFON_RANDUM_MIN,
                'acc_offon_randum_max' : ACC_OFFON_RANDUM_MAX,
                'adb_ss_enable' : ADB_SS_ENABLE,
                'asee_to_teststop' : ASEE_TO_TESTSTOP,
                'camera_enable': CAMERA_ENABLE,
                'camera_id': CAMERA_ID,
                'camera_frame_w': CAMERA_FRAME_WIDTH,
                'camera_frame_h': CAMERA_FRAME_HEIGHT,
                'teams_enable' : TEAMS_ENABLE,
                'teams_url' : TEAMS_URL,
                'teams_title' : TEAMS_TITLE,
            }
    else:
        config['BASE'] = {
            'ucom_com': UCOM_COM_PORT,
            'qnx_com': QNX_COM_PORT,
            'sail_com': SAIL_COM_PORT,
            'android_com': ANDROID_COM_PORT,
            'pika_com': PIKA_COM_PORT,
            'tool_mode': TOOL_MODE,
            'dump_mode': DUMP_MODE,
            'debug_mode': DEBUG_MODE,
            'add_sail_log': ADD_SAILLOG_ON,
            'sail_debug_disable': SAIL_DEBUG_MODE_DISABLE,
            'sleep_check': SLEEP_CHECK,
            'test_mode' : TEST_MODE,
            'acc_offon_time' : ACC_OFFON_TIME,
            'acc_offon_randum_min' : ACC_OFFON_RANDUM_MIN,
            'acc_offon_randum_max' : ACC_OFFON_RANDUM_MAX,
            'adb_ss_enable' : ADB_SS_ENABLE,
            'asee_to_teststop' : ASEE_TO_TESTSTOP,
            'camera_enable': CAMERA_ENABLE,
            'camera_id': CAMERA_ID,
            'camera_frame_w': CAMERA_FRAME_WIDTH,
            'camera_frame_h': CAMERA_FRAME_HEIGHT,
            'teams_enable' : TEAMS_ENABLE,
            'teams_url' : TEAMS_URL,
            'teams_title' : TEAMS_TITLE,
        }
        with open('config.ini', 'w',encoding='shift_jis') as configfile:
            config.write(configfile)

def ini_file_update():
    
    config['BASE'] = {
        'ucom_com': UCOM_COM_PORT,
        'qnx_com': QNX_COM_PORT,
        'sail_com': SAIL_COM_PORT,
        'android_com': ANDROID_COM_PORT,
        'pika_com': PIKA_COM_PORT,
        'tool_mode': TOOL_MODE,
        'dump_mode': DUMP_MODE,
        'debug_mode': DEBUG_MODE,
        'add_sail_log': ADD_SAILLOG_ON,
        'sail_debug_disable': SAIL_DEBUG_MODE_DISABLE,
        'sleep_check': SLEEP_CHECK,
        'test_mode' : TEST_MODE,
        'acc_offon_time' : ACC_OFFON_TIME,
        'acc_offon_randum_min' : ACC_OFFON_RANDUM_MIN,
        'acc_offon_randum_max' : ACC_OFFON_RANDUM_MAX,
        'adb_ss_enable' : ADB_SS_ENABLE,
        'asee_to_teststop' : ASEE_TO_TESTSTOP,
        'camera_enable': CAMERA_ENABLE,
        'camera_id': CAMERA_ID,
        'camera_frame_w': CAMERA_FRAME_WIDTH,
        'camera_frame_h': CAMERA_FRAME_HEIGHT,
        'teams_enable' : TEAMS_ENABLE,
        'teams_url' : TEAMS_URL,
        'teams_title' : TEAMS_TITLE,
    }
    with open('config.ini', 'w',encoding='shift_jis') as configfile:
        config.write(configfile)

def get_enable_cameralist():

    camera_enable_list = []

    for camera_id in range(10):
        try:
            camera = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
            if camera.isOpened(): 
                camera_enable_list.append(camera_id)
            else:
                pass
            camera.release()
        except Exception as e:
           pass

    os.system('cls')
    
    return camera_enable_list

#使用可能なCOMポートのリストを返す
def get_available_com_ports():
    ports = serial.tools.list_ports.comports()
    available_ports = [port.device for port in ports]
    return available_ports

#折り返し対象のログを選択するwindow
def gui_orkaesi_logselect(root):
    
    #追加ウインドウの定義
    select_window = tk.Toplevel(root)
    
    # 中央に配置するためのxとy座標を計算
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    win_width = 625
    win_height = 300
    x = (screen_width // 2) - (win_width // 2)
    y = (screen_height // 2) - (win_height // 2)

    #ウィンドウタイトル、サイズ、位置の設定
    select_window.title('折り返し対象ログ選択')
    select_window.geometry(f'{win_width}x{win_height}+{x}+{y}')
    
    #×ボタン押下時の設定
    def select_window_click_close():
        select_window.destroy()
    select_window.protocol("WM_DELETE_WINDOW", select_window_click_close)
    
    #フレームの設定
    labelframe_log = tk.LabelFrame(select_window, text = '折り返し(ポイント指定)の対象のログを選択',labelanchor='n')
    frame_selectbtn = tk.Frame(select_window)
    
    #チェックボックスの設定
    size = len(suspend_trigger_list)
    bln = [None] * size
    chk = [None] * size
    for i in range (0,size):
        bln[i] = tk.BooleanVar()
        bln[i].set(True)
        chk[i] = tk.Checkbutton(labelframe_log, variable=bln[i], text=suspend_trigger_list[i][1], anchor=tk.W)
    
    #決定ボタンの設定
    def fnc_getselectdata():
        global suspend_trigger_list
        #チェックのカウントを確認
        count = 0
        for i in range (0,len(bln)):
            if bln[i].get() == True:
                count += 1
        if count == 0:
            messagebox.showwarning(title="注意", message="1つ以上、ログを選択してください")
        else:
            for i in range (0,len(suspend_trigger_list)):
                suspend_trigger_list[i][5] = bln[i].get()
            select_window.destroy()
    select_btn = tk.Button(frame_selectbtn, text="OK", command=fnc_getselectdata, height=1, width=25,pady = 3)

    #フレームの配置
    labelframe_log.grid(row=0,column=0)
    frame_selectbtn.grid(row=1,column=0)
    
    #チェックボックスの配置
    for i in range (0,size):
        chk[i].grid(row=i,column=0)
    
    #決定ボタンの配置
    select_btn.grid(row=0,column=0)
    
    select_window.mainloop()

#各種COMポート設定、テストの動作を設定するwindow
def gui_portsetting():
    global CAMERA_ENABLE
    global CAMERA_ID
    ports = get_available_com_ports()
    toolmode = [[0, 1],['ISP', 'ICB']]
    
    camera_ids = get_enable_cameralist()
    if len(camera_ids) == 0:
        camera_ids.append(0)
        camera_set = [[0],['無効']]
        CAMERA_ENABLE = 0
        CAMERA_ID = 0
    else:
        camera_set = [[0, 1],['無効', '有効']]
    sail_addlog = [[0, 1],['通常ログ', '追加ログ']]
    saildebugmode = [[0, 1],['有効', '無効']]
    dumpmode = [[0, 1, 2],['dump無効', 'minidump','fulldump']]
    testmode = [[0],['通常のサスレジ']]
    acc_offon_times = [i for i in range(1, 301)]
    acc_offon_randam_mins = [i for i in range(1, 301)]
    acc_offon_randam_maxs = [i for i in range(1, 301)]
    sleepcheck = [[0, 1],['無効', '有効']]
    adb_ss_enable_list = [[0, 1],['無効', '有効']]
    teams_set = [[0, 1],['無効', '有効']]
    
    root = tk.Tk()
    # 中央に配置するためのxとy座標を計算
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    
    win_width = 1350
    win_height = 450
    x = (screen_width // 2) - (win_width // 2)
    y = (screen_height // 2) - (win_height // 2)

    #ウィンドウタイトル、サイズ、位置の設定
    root.title('suspend_resume_test.py')
    root.geometry(f'{win_width}x{win_height}+{x}+{y}')

    #ラベルフレーム設定
    labelframe_port = tk.LabelFrame(root, text = 'ポート設定',labelanchor='n')
    labelframe_test = tk.LabelFrame(root, text = 'テスト種別設定',labelanchor='n')
    labelframe_add = tk.LabelFrame(root, text = '追加動作設定',labelanchor='n')
    labelframe_camera = tk.LabelFrame(root, text = 'カメラ設定',labelanchor='n')
    labelframe_orikaesi = tk.LabelFrame(root, text = '折り返しテスト設定',labelanchor='n')
    labelframe_log = tk.LabelFrame(root, text = 'suspend折り返し(ポイント指定)の対象のログを選択',labelanchor='n')
    labelframe_log2 = tk.LabelFrame(root, text = 'resume折り返し(ポイント指定)の対象のログを選択',labelanchor='n')
    labelframe_teams = tk.LabelFrame(root, text = 'Teamsへの自動通知設定',labelanchor='n')
    frame_btn = tk.Frame(root)
    #フレーム配置 20行*4列
    labelframe_port.grid(row=0,column=0,rowspan=6,padx=3,pady=2,sticky=tk.N)
    labelframe_test.grid(row=6,column=0,rowspan=3, padx=3,pady=2,sticky=tk.N)
    labelframe_add.grid(row=0,column=1,rowspan=6, padx=3,pady=2,sticky=tk.N)
    labelframe_camera.grid(row=9,column=0,rowspan=3, padx=3,pady=2,sticky=tk.N)
    labelframe_orikaesi.grid(row=7,column=1,rowspan=4, padx=3,pady=2,sticky=tk.N)
    labelframe_log.grid(row=0,column=2,rowspan=10, padx=3,pady=2,sticky=tk.N)
    labelframe_log2.grid(row=0,column=3,rowspan=16, padx=3,pady=2,sticky=tk.N)
    labelframe_teams.grid(row=19,column=0,rowspan=4,columnspan=4, padx=3,pady=2,sticky=tk.N)
    frame_btn.grid(row=23,column=0,columnspan=4, padx=3,pady=2,sticky=tk.N)
    
    #ラベルの設定(ポート設定)
    label_ucom = tk.Label(labelframe_port, text="uCOM: ",height=1, width=22)
    label_qnx = tk.Label(labelframe_port, text="QNX: ",height=1, width=22)
    label_sail = tk.Label(labelframe_port, text="SAIL: ",height=1, width=22)
    label_android = tk.Label(labelframe_port, text="android: ",height=1, width=22)
    label_pika = tk.Label(labelframe_port, text="ぴかぱち: ",height=1, width=22)
    
    #コンボボックスの設定(ポート設定)
    combobox_ucom = ttk.Combobox(labelframe_port, height=10, width=20, values=ports)
    combobox_qnx = ttk.Combobox(labelframe_port, height=10, width=20, values=ports)
    combobox_sail = ttk.Combobox(labelframe_port, height=10, width=20, values=ports)
    combobox_android = ttk.Combobox(labelframe_port, height=10, width=20, values=ports)
    combobox_pika = ttk.Combobox(labelframe_port, height=10, width=20, values=ports)
    
    #ラベルの配置(ポート設定)
    label_ucom.grid(column=0,row=0, pady=1)
    label_qnx.grid(column=0,row=1, pady=1)
    label_sail.grid(column=0,row=2, pady=1)
    label_android.grid(column=0,row=3, pady=1)
    label_pika.grid(column=0,row=4, pady=1)
    
    #コンボボックスの配置(ポート設定)
    combobox_ucom.grid(column=1,row=0, pady=1)
    combobox_qnx.grid(column=1,row=1, pady=1)
    combobox_sail.grid(column=1,row=2, pady=1)
    combobox_android.grid(column=1,row=3, pady=1)
    combobox_pika.grid(column=1,row=4, pady=1)
    
    #ラベルの設定(テスト種別設定)
    label_mode = tk.Label(labelframe_test, text="Soc種別: ",height=1, width=13)
    label_testmode = tk.Label(labelframe_test, text="Test種別: ",height=1, width=13)
    
    #コンボボックスの設定(テスト種別設定)
    combobox_toolmode = ttk.Combobox(labelframe_test, height=10, width=30, values=toolmode[1])
    combobox_testmode = ttk.Combobox(labelframe_test, height=10, width=30, values=testmode[1])
    
    #ラベルの配置(テスト種別設定)
    label_mode.grid(column=0,row=0, pady=1)
    label_testmode.grid(column=0,row=1, pady=1)
    
    #コンボボックスの配置(テスト種別設定)
    combobox_toolmode.grid(column=1,row=0, pady=1)
    combobox_testmode.grid(column=1,row=1, pady=1)
    
    #ラベルの設定(追加動作設定)
    label_sail_addlog = tk.Label(labelframe_add, text="sail log設定: ",height=1, width=25)
    label_saildebugmode = tk.Label(labelframe_add, text="sail debug設定: ",height=1, width=25)
    label_ramdump = tk.Label(labelframe_add, text="ramdump設定: ",height=1, width=25)
    label_sleepcheck = tk.Label(labelframe_add, text="suspend失敗時にコマンド送信: ",height=1, width=25)
    label_adb_ss_enable = tk.Label(labelframe_add, text="resume時にadb screenshot取得: ",height=1, width=25)
    
    #コンボボックスの設定(追加動作設定)
    combobox_sail_addlog = ttk.Combobox(labelframe_add, height=10, width=17, values=sail_addlog[1])
    combobox_saildebugmode = ttk.Combobox(labelframe_add, height=10, width=17, values=saildebugmode[1])
    combobox_ramdump = ttk.Combobox(labelframe_add, height=10, width=17, values=dumpmode[1])
    combobox_sleepcheck = ttk.Combobox(labelframe_add, height=10, width=17, values=sleepcheck[1])
    combobox_adb_ss_enable = ttk.Combobox(labelframe_add, height=10, width=17, values=adb_ss_enable_list[1])
    
    #ラベルの配置(追加動作設定)
    label_sail_addlog.grid(  column=0,row=0, pady=1)
    label_saildebugmode.grid(column=0,row=1, pady=1)
    label_ramdump.grid(      column=0,row=2, pady=1)
    label_sleepcheck.grid(   column=0,row=3, pady=1)
    label_adb_ss_enable.grid(column=0,row=4, pady=1)
    
    #コンボボックスの配置(追加動作設定)
    combobox_sail_addlog.grid(  column=1,row=0, pady=1)
    combobox_saildebugmode.grid(column=1,row=1, pady=1)
    combobox_ramdump.grid(      column=1,row=2, pady=1)
    combobox_sleepcheck.grid(   column=1,row=3, pady=1)
    combobox_adb_ss_enable.grid(column=1,row=4, pady=1)
    
    #ラベルの設定(カメラ設定)
    label_camera = tk.Label(labelframe_camera, text="カメラ設定: ",height=1, width=20)
    label_cameraid = tk.Label(labelframe_camera, text="カメラID: ",height=1, width=20)
    
    #コンボボックスの設定(カメラ設定)
    combobox_camera = ttk.Combobox(labelframe_camera, height=10, width=22, values=camera_set[1])
    combobox_cameraid = ttk.Combobox(labelframe_camera, height=10, width=22, values=camera_ids)
    
    #ラベルの配置(カメラ設定)
    label_camera.grid(column=0,row=0, pady=1)
    label_cameraid.grid(column=0,row=1, pady=1)
    
    #コンボボックスの配置(カメラ設定)
    combobox_camera.grid(column=1,row=0, pady=1)
    combobox_cameraid.grid(column=1,row=1, pady=1)
    
    #ラベルの設定(折り返しテスト設定)
    label_accofontime = tk.Label(labelframe_orikaesi, text="折り返し固定時間(sec): ",height=1, width=20)
    label_accofonrandummin = tk.Label(labelframe_orikaesi, text="折り返しランダム最小時間(sec): ",height=1, width=22)
    label_accofonrandummax = tk.Label(labelframe_orikaesi, text="折り返しランダム最大時間(sec): ",height=1, width=22)
        
    #コンボボックスの設定(折り返しテスト設定)
    combobox_accofontime = ttk.Combobox(labelframe_orikaesi, height=10, width=20, values=acc_offon_times)
    combobox_accofonrandummin = ttk.Combobox(labelframe_orikaesi, height=10, width=20, values=acc_offon_randam_mins)
    combobox_accofonrandummax = ttk.Combobox(labelframe_orikaesi, height=10, width=20, values=acc_offon_randam_maxs)
    
    #ラベルの配置(折り返しテスト設定)
    label_accofontime.grid(column=0,row=0, pady=1)
    label_accofonrandummin.grid(column=0,row=1, pady=1)
    label_accofonrandummax.grid(column=0,row=2, pady=1)
    
    #コンボボックスの配置(折り返しテスト設定)
    combobox_accofontime.grid(column=1,row=0, pady=1)
    combobox_accofonrandummin.grid(column=1,row=1, pady=1)
    combobox_accofonrandummax.grid(column=1,row=2, pady=1)
    
    #チェックボックスの設定(サスレジ折り返し(ポイント指定)の対象のログを選択)
    size = len(suspend_trigger_list)
    bln = [None] * size
    chk = [None] * size
    for i in range (0,size):
        bln[i] = tk.BooleanVar()
        bln[i].set(True)
        chk[i] = tk.Checkbutton(labelframe_log, variable=bln[i], text=suspend_trigger_list[i][1], height=1, width=45, anchor=tk.W)
    
    #チェックボックスの配置
    for i in range (0,size):
        chk[i].grid(row=i,column=0)

    #チェックボックスの設定(レジューム折り返し(ポイント指定)の対象のログを選択)
    size = len(resume_trigger_list)
    bln2 = [None] * size
    chk2 = [None] * size
    for i in range (0,size):
        bln2[i] = tk.BooleanVar()
        bln2[i].set(True)
        chk2[i] = tk.Checkbutton(labelframe_log2, variable=bln2[i], text=resume_trigger_list[i][1], height=1, width=45, anchor=tk.W)
    
    #チェックボックスの配置
    for i in range (0,size):
        chk2[i].grid(row=i,column=0)

    #ラベルの設定(Teams設定)
    label_teams_enable = tk.Label(labelframe_teams, text="Teams通知設定: ",height=1, width=13)
    label_teams_url = tk.Label(labelframe_teams, text="URL: ",height=1, width=13)
    label_teams_title = tk.Label(labelframe_teams, text="通知Title: ",height=1, width=13)
    
    #コンボボックスの設定(Teams設定)
    combobox_teams_enable = ttk.Combobox(labelframe_teams, height=10, width=17, values=teams_set[1])
    
    #入力欄の設定(Teams設定)
    entry_teams_title = tk.Entry(labelframe_teams, width=202)
    entry_teams_url = tk.Entry(labelframe_teams, width=202)
    
    #ボタンの設定(Teams設定)
    def func_btn_teams_send():
        global TEAMS_ENABLE
        
        TEAMS_ENABLE = adb_ss_enable_list[0][combobox_teams_enable.current()]
        
        if combobox_teams_enable.get() != '有効':
            messagebox.showwarning(title="注意", message="Teams通知設定を有効にしてください")
        elif entry_teams_url.get() == '':
            messagebox.showwarning(title="注意", message="Teamsへ送信するURLが記載されていません。")
        else:
            url = entry_teams_url.get()
            title = entry_teams_title.get()
            susres_test_info(into_url=url, into_title=title, into_info='テスト送信')
    
    btn_teams_send = tk.Button(labelframe_teams, text='URLへテスト送信', command=func_btn_teams_send)

    #Teams設定フレーム内の配置
    label_teams_enable.grid(column=0,row=0,pady=1)
    label_teams_title.grid(column=0,row=1,pady=1)
    label_teams_url.grid(column=0,row=2,pady=1)
    
    combobox_teams_enable.grid(column=1,row=0,padx=5,pady=1,sticky="w")
    entry_teams_title.grid(column=1,row=1,padx=5,pady=1,sticky="w")
    entry_teams_url.grid(column=1,row=2,padx=5,pady=1,sticky="w")
    
    btn_teams_send.grid(column=1,row=3,pady=1, rowspan=2,sticky="w")
    
    # デフォルト状態の反映
    for i in range(0,len(ports),1):
        if ports[i] == UCOM_COM_PORT:
            combobox_ucom.set(UCOM_COM_PORT)
        elif ports[i] == QNX_COM_PORT:
            combobox_qnx.set(QNX_COM_PORT)
        elif ports[i] == SAIL_COM_PORT:
            combobox_sail.set(SAIL_COM_PORT)
        elif ports[i] == ANDROID_COM_PORT:
            combobox_android.set(ANDROID_COM_PORT)
        elif ports[i] == PIKA_COM_PORT:
            combobox_pika.set(PIKA_COM_PORT)
    for i in range(0,len(toolmode[0]),1):
        if toolmode[0][i] == TOOL_MODE:
            combobox_toolmode.set(toolmode[1][i])
    for i in range(0,len(camera_set[0]),1):
        if camera_set[0][i] == CAMERA_ENABLE:
            combobox_camera.set(camera_set[1][i])
    for i in range(0,len(camera_ids),1):
        if camera_ids[i] == CAMERA_ID:
            combobox_cameraid.set(CAMERA_ID)
    for i in range(0,len(sail_addlog[0]),1):
        if sail_addlog[0][i] == ADD_SAILLOG_ON:
            combobox_sail_addlog.set(sail_addlog[1][i])
    for i in range(0,len(saildebugmode[0]),1):
        if saildebugmode[0][i] == SAIL_DEBUG_MODE_DISABLE:
            combobox_saildebugmode.set(saildebugmode[1][i])
    for i in range(0,len(dumpmode[0]),1):
        if dumpmode[0][i] == DUMP_MODE:
            combobox_ramdump.set(dumpmode[1][i])
    for i in range(0,len(sleepcheck[0]),1):
        if sleepcheck[0][i] == SLEEP_CHECK:
            combobox_sleepcheck.set(sleepcheck[1][i])
    for i in range(0,len(testmode[0]),1):
        if testmode[0][i] == TEST_MODE:
            combobox_testmode.set(testmode[1][i])
    for i in range(0,len(acc_offon_times),1):
        if acc_offon_times[i] == ACC_OFFON_TIME:
            combobox_accofontime.set(ACC_OFFON_TIME)
    for i in range(0,len(acc_offon_randam_mins),1):
        if acc_offon_randam_mins[i] == ACC_OFFON_RANDUM_MIN:
            combobox_accofonrandummin.set(ACC_OFFON_RANDUM_MIN)
    for i in range(0,len(acc_offon_randam_maxs),1):
        if acc_offon_randam_maxs[i] == ACC_OFFON_RANDUM_MAX:
            combobox_accofonrandummax.set(ACC_OFFON_RANDUM_MAX)
    for i in range(0,len(adb_ss_enable_list[0]),1):
        if adb_ss_enable_list[0][i] == ADB_SS_ENABLE:
            combobox_adb_ss_enable.set(adb_ss_enable_list[1][i])
    for i in range(0,len(teams_set[0]),1):
        if teams_set[0][i] == TEAMS_ENABLE:
            combobox_teams_enable.set(teams_set[1][i])
    if TEAMS_URL != "":
        entry_teams_url.insert(0, TEAMS_URL)
    if TEAMS_TITLE != "":
        entry_teams_title.insert(0, TEAMS_TITLE)

    def fnc_getselectdata():
        global UCOM_COM_PORT
        global QNX_COM_PORT
        global SAIL_COM_PORT
        global ANDROID_COM_PORT
        global PIKA_COM_PORT
        global TOOL_MODE
        global CAMERA_ENABLE
        global CAMERA_ID
        global ADD_SAILLOG_ON
        global SAIL_DEBUG_MODE_DISABLE
        global DUMP_MODE
        global SLEEP_CHECK
        global TEST_MODE
        global ACC_OFFON_TIME
        global ACC_OFFON_RANDUM_MIN
        global ACC_OFFON_RANDUM_MAX
        global ADB_SS_ENABLE
        global TEAMS_ENABLE
        global TEAMS_URL
        global TEAMS_TITLE
        global suspend_trigger_list
        global resume_trigger_list
        #折り返し(ポイント指定)の対象のログのカウントを確認
        count = 0
        for i in range (0,len(bln)):
            if bln[i].get() == True:
                count += 1
        count2 = 0
        for i in range (0,len(bln2)):
            if bln2[i].get() == True:
                count2 += 1
        if combobox_testmode.get() == '':
            messagebox.showwarning(title="注意", message="Test種別が選択されていません")
        elif count == 0 and testmode[0][combobox_testmode.current()] == 1:
            messagebox.showwarning(title="注意", message="suspend折り返し(ポイント指定)の対象のログを一つ以上選択してください")
        elif count2 == 0 and testmode[0][combobox_testmode.current()] == 4:
            messagebox.showwarning(title="注意", message="resume折り返し(ポイント指定)の対象のログを一つ以上選択してください")
        elif combobox_ucom.get() == '':
            messagebox.showwarning(title="注意", message="uComのCOMポートが選択されていません")
        elif combobox_qnx.get() == '':
            messagebox.showwarning(title="注意", message="QNXのCOMポートが選択されていません")
        elif combobox_sail.get() == '':
            messagebox.showwarning(title="注意", message="SailのCOMポートが選択されていません")
        elif combobox_android.get() == '':
            messagebox.showwarning(title="注意", message="androidのCOMポートが選択されていません")
        elif combobox_pika.get() == '':
            messagebox.showwarning(title="注意", message="ピカパチのCOMポートが選択されていません")
        elif combobox_toolmode.get() == '':
            messagebox.showwarning(title="注意", message="Soc種別が選択されていません")
        elif entry_teams_url.get() == '' and  combobox_teams_enable.get() == '有効':
            messagebox.showwarning(title="注意", message="Teamsへ送信するURLが記載されていません。不要の場合はTeams通知設定を無効に設定してください。")
        else:
        #各設定を反映し、ウィンドウを閉じる
            if testmode[0][combobox_testmode.current()]== 1:
                for i in range (0,len(suspend_trigger_list)):
                    suspend_trigger_list[i][5] = bln[i].get()
            
            if testmode[0][combobox_testmode.current()]== 4:
                for i in range (0,len(resume_trigger_list)):
                    resume_trigger_list[i][5] = bln2[i].get()
            
            if combobox_ucom.get() != '':
                UCOM_COM_PORT = combobox_ucom.get()
            if combobox_qnx.get() != '':
                QNX_COM_PORT = combobox_qnx.get()
            if combobox_sail.get() != '':
                SAIL_COM_PORT = combobox_sail.get()
            if combobox_android.get() != '':
                ANDROID_COM_PORT = combobox_android.get()
            if combobox_pika.get() != '':
                PIKA_COM_PORT = combobox_pika.get()
            if combobox_toolmode.get() != '':
                TOOL_MODE = toolmode[0][combobox_toolmode.current()]
            if combobox_camera.get() != '':
                CAMERA_ENABLE = camera_set[0][combobox_camera.current()]
            if combobox_cameraid.get() != '':
                CAMERA_ID = int(combobox_cameraid.get())
            if combobox_sail_addlog.get() != '':
                ADD_SAILLOG_ON = sail_addlog[0][combobox_sail_addlog.current()]
            if combobox_saildebugmode.get() != '':
                SAIL_DEBUG_MODE_DISABLE = saildebugmode[0][combobox_saildebugmode.current()]
            if combobox_ramdump.get() != '':
                DUMP_MODE = dumpmode[0][combobox_ramdump.current()]
            if combobox_sleepcheck.get() != '':
                SLEEP_CHECK = sleepcheck[0][combobox_sleepcheck.current()]
            if combobox_testmode.get() != '':
                TEST_MODE = testmode[0][combobox_testmode.current()]
            if combobox_accofontime.get() != '':
                ACC_OFFON_TIME = int(combobox_accofontime.get())
            if combobox_accofonrandummin.get() != '':
                ACC_OFFON_RANDUM_MIN = int(combobox_accofonrandummin.get())
            if combobox_accofonrandummax.get() != '':
                ACC_OFFON_RANDUM_MAX = int(combobox_accofonrandummax.get())
            if combobox_adb_ss_enable.get() != '':
                ADB_SS_ENABLE = adb_ss_enable_list[0][combobox_adb_ss_enable.current()]
            if combobox_teams_enable.get() != '':
                TEAMS_ENABLE = adb_ss_enable_list[0][combobox_teams_enable.current()]
            if entry_teams_url.get() != '':
                TEAMS_URL = entry_teams_url.get()
            if entry_teams_title.get() != '':
                TEAMS_TITLE = entry_teams_title.get()

            
            ini_file_update()
            root.destroy()
    
    btn = tk.Button(frame_btn, text="OK", command=fnc_getselectdata, height=1, width=25,pady = 3)
    btn.grid(column=0, row=0)
    
    def click_close():
        root.destroy()
        sys.exit()

    root.protocol("WM_DELETE_WINDOW", click_close)
    root.mainloop()


#cmd送信
def consol_cmd(command_list, timeout=None):
    result = RESULT_NG
    res = ''
    try:
        #subprocessでコマンドを送信する場合 
        process_result = subprocess.run(command_list, capture_output=True, text=True, check=True, shell=False, timeout=timeout)
        res = process_result.stdout
        result = RESULT_OK
    except subprocess.TimeoutExpired:
        result = RESULT_TO
    except subprocess.CalledProcessError as e:
        result = RESULT_NG
    return result, res

def adb_screenshot(filename):
    #androidにadb接続の前処理を実行
    senddata1 = 'su'
    senddata2 = 'setprop vendor.sys.usb.adb.disabled 0'
    senddata3 = 'echo "peripheral" > /sys/devices/platform/soc/a600000.ssusb/mode'
    q_android.put((EV_ANDROID_SER_WRITE, senddata1))
    q_android.put((EV_ANDROID_SER_WRITE, senddata2))
    q_android.put((EV_ANDROID_SER_WRITE, senddata3))
    q_android.join()
    
    time.sleep(5)
    
    #adbでスクリーンショットを取得
    os.makedirs(fr'{logfpath}/adb_ss_{str(log_index)}', exist_ok=True)
    cmdlist0 = ['adb','devices']
    cmdlist1 = ['adb', 'shell', 'screencap', '-p', '/sdcard/screen.png']
    cmdlist2 = ['adb', 'pull', '/sdcard/screen.png', fr'{logfpath}/adb_ss_{str(log_index)}/{datastr_get()}_{filename}']
    cmdlist3 = ['adb', 'shell', 'rm', '/sdcard/screen.png']
    result, resmsg = consol_cmd(cmdlist0, 10)
    result, resmsg = consol_cmd(cmdlist1, 10)
    result, resmsg = consol_cmd(cmdlist2, 10)
    result, resmsg = consol_cmd(cmdlist3, 10)

    senddata1 = 'su'
    senddata2 = 'setprop vendor.sys.usb.adb.disabled 1'
    senddata3 = 'echo "normal" > /sys/devices/platform/soc/a600000.ssusb/mode'
    q_android.put((EV_ANDROID_SER_WRITE, senddata1))
    q_android.put((EV_ANDROID_SER_WRITE, senddata2))
    q_android.put((EV_ANDROID_SER_WRITE, senddata3))
    q_android.join()


#日時取得
def datastr_get():
    
    dt_now = datetime.datetime.now()
    
    return dt_now.strftime('%Y%m%d_%H%M%S')

#日時取得-ログのタイムスタンプ用
def timestamp_get():
    
    dt_now = datetime.datetime.now()
    
    time = dt_now.strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp = "[" + time[:-3] + "] "
    return timestamp


def ucom_serial_communication():
    global ucom_console_list
    global suspend_wait_flag
    global resume_wait_flag
    
    ucom_contine_flag = True
    ucom_timeout_count = 0
    while tool_state == TOOL_STATE_RUN:
        try:
            if ucom_contine_flag == True:
                ser_ucom = serial.Serial(UCOM_COM_PORT, 115200, timeout=1)
                ucom_contine_flag = False
            ucom_readdata = ser_ucom.readline().decode('utf-8')
            if ucom_readdata:
                ucom_timeout_count = 0
                ucom_readdata = ucom_readdata.strip()
                if ucom_readdata:
                    lock1.acquire()
                    ucom_console_list.append(ucom_readdata)
                    if len(ucom_console_list) > 1000:
                        ucom_console_list.pop(0)
                    lock1.release()
                    timestamp = timestamp_get()
                    ucom_error_monitor(ucom_readdata,timestamp)
                    with open(logfpath + '/ucom_' + str(log_index) + '.log', 'a',encoding="utf-8") as ucom_f:
                        ucom_f.write(timestamp + ucom_readdata + "\n")
                    if suspend_trigger_list[suspend_select_trigger][0] == 'ucom':
                        if suspend_trigger_list[suspend_select_trigger][1] in ucom_readdata:
                            suspend_wait_flag = 0
                            
                    if resume_trigger_list[resume_select_trigger][0] == 'ucom':
                        if resume_trigger_list[resume_select_trigger][1] in ucom_readdata:
                            resume_wait_flag = 0
            else:
                ucom_timeout_count += ucom_timeout_count
                if ucom_timeout_count > 500:
                    ser_ucom.close()
                    ser_ucom = serial.Serial(UCOM_COM_PORT, 115200, timeout=1)
                    timestamp = timestamp_get()
                    testlog_write(TESTLOG_WRITE, '[ucom]     :' + timestamp_get() + 'serial通信途絶(500sec).' )
                    ucom_timeout_count = 0
                
            if not q_ucom.empty():
                ucom_evid, ucom_evdata = q_ucom.get()
                if ucom_evid == EV_UCOM_SER_WRITE:
                    ucom_senddata = ucom_evdata + "\r"
                    ser_ucom.write(ucom_senddata.encode('utf-8'))
                else:
                    pass
                q_ucom.task_done()
        except UnicodeDecodeError as e:
            pass
        except UnicodeEncodeError as e:
            pass
        except serial.SerialException as e:
            if ser_ucom.isOpen() == True:
                ser_ucom.close()
            testlog_write(TESTLOG_WRITE, '[ucom]     :' + timestamp_get() + 'serial通信接続失敗,5秒後に再接続実施' )
            ucom_contine_flag = True
            time.sleep(5) 
    if ser_ucom.isOpen() == True:
        ser_ucom.close()


def qnx_serial_communication():
    global qnx_console_list
    global suspend_wait_flag
    global resume_wait_flag
    
    qnx_contine_flag = True
    qnx_timeout_count = 0
    while tool_state == TOOL_STATE_RUN:
        try:
            if qnx_contine_flag == True:
                ser_qnx = serial.Serial(QNX_COM_PORT, 115200, timeout=1)
                qnx_contine_flag = False
            qnx_readdata = ser_qnx.readline().decode('utf-8')
            if qnx_readdata:
                qnx_timeout_count = 0
                qnx_readdata = qnx_readdata.strip()
                if qnx_readdata:
                    lock2.acquire()
                    qnx_console_list.append(qnx_readdata)
                    if len(qnx_console_list) > 1000:
                        qnx_console_list.pop(0)
                    lock2.release()
                    timestamp = timestamp_get()
                    qnx_error_monitor(qnx_readdata,timestamp)
                    with open(logfpath + '/qnx_' + str(log_index) + '.log', 'a',encoding="utf-8") as qnx_f:
                        qnx_f.write(timestamp + qnx_readdata + "\n")
                    if suspend_trigger_list[suspend_select_trigger][0] == 'qnx':
                        if suspend_trigger_list[suspend_select_trigger][1] in qnx_readdata:
                            suspend_wait_flag = 0
                            
                    if resume_trigger_list[resume_select_trigger][0] == 'qnx':
                        if resume_trigger_list[resume_select_trigger][1] in qnx_readdata:
                            resume_wait_flag = 0
            else:
                qnx_timeout_count += qnx_timeout_count
                if qnx_timeout_count > 500:
                    ser_qnx.close()
                    ser_qnx = serial.Serial(QNX_COM_PORT, 115200, timeout=1)
                    timestamp = timestamp_get()
                    testlog_write(TESTLOG_WRITE, '[qnx]     :' + timestamp_get() + 'serial通信途絶(500sec).' )
                    qnx_timeout_count = 0
                
            if not q_qnx.empty():
                qnx_evid, qnx_evdata = q_qnx.get()
                if qnx_evid == EV_QNX_SER_WRITE:
                    qnx_senddata = qnx_evdata + "\r"
                    ser_qnx.write(qnx_senddata.encode('utf-8'))
                else:
                    pass
                q_qnx.task_done()
        except UnicodeDecodeError as e:
            pass
        except UnicodeEncodeError as e:
            pass
        except serial.SerialException as e:
            if ser_qnx.isOpen() == True:
                ser_qnx.close()
            testlog_write(TESTLOG_WRITE, '[qnx]     :' + timestamp_get() + 'serial通信接続失敗,5秒後に再接続実施' )
            qnx_contine_flag = True
            time.sleep(5) 
    if ser_qnx.isOpen() == True:
        ser_qnx.close()


def android_serial_communication():
    global android_console_list
    
    android_contine_flag = True
    android_timeout_count = 0
    while tool_state == TOOL_STATE_RUN:
        try:
            if android_contine_flag == True:
                ser_android = serial.Serial(ANDROID_COM_PORT, 115200, timeout=1)
                android_contine_flag = False
            android_readdata = ser_android.readline().decode('utf-8')
            if android_readdata:
                android_timeout_count = 0
                android_readdata = android_readdata.strip()
                if android_readdata:
                    lock3.acquire()
                    android_console_list.append(android_readdata)
                    if len(android_console_list) > 1000:
                        android_console_list.pop(0)
                    lock3.release()
                    timestamp = timestamp_get()
                    android_error_monitor(android_readdata,timestamp)
                    with open(logfpath + '/android_' + str(log_index) + '.log', 'a',encoding="utf-8") as android_f:
                        android_f.write(timestamp + android_readdata + "\n")
            else:
                android_timeout_count += android_timeout_count
                if android_timeout_count > 500:
                    ser_android.close()
                    ser_android = serial.Serial(ANDROID_COM_PORT, 115200, timeout=1)
                    timestamp = timestamp_get()
                    testlog_write(TESTLOG_WRITE, '[android] :' + timestamp_get() + 'serial通信途絶(500sec).' )
                    android_timeout_count = 0
                
            if not q_android.empty():
                android_evid, android_evdata = q_android.get()
                if android_evid == EV_ANDROID_SER_WRITE:
                    android_senddata = android_evdata + "\r"
                    ser_android.write(android_senddata.encode('utf-8'))
                else:
                    pass
                q_android.task_done()
        except UnicodeDecodeError as e:
            pass
        except UnicodeEncodeError as e:
            pass
        except serial.SerialException as e:
            if ser_android.isOpen() == True:
                ser_android.close()
            testlog_write(TESTLOG_WRITE, '[android] :' + timestamp_get() + 'serial通信接続失敗,5秒後に再接続実施' )
            android_contine_flag = True
            time.sleep(5) 
    if ser_android.isOpen() == True:
        ser_android.close()


def sail_serial_communication():
    global sail_console_list
    
    sail_contine_flag = True
    sail_timeout_count = 0
    while tool_state == TOOL_STATE_RUN:
        try:
            if sail_contine_flag == True:
                ser_sail = serial.Serial(SAIL_COM_PORT, 115200, timeout=1)
                sail_contine_flag = False
            sail_readdata = ser_sail.readline().decode('utf-8')
            if sail_readdata:
                sail_timeout_count = 0
                sail_readdata = sail_readdata.strip()
                if sail_readdata:
                    lock4.acquire()
                    sail_console_list.append(sail_readdata)
                    if len(sail_console_list) > 1000:
                        sail_console_list.pop(0)
                    lock4.release()
                    timestamp = timestamp_get()
                    sail_error_monitor(sail_readdata,timestamp)
                    with open(logfpath + '/sail_' + str(log_index) + '.log', 'a',encoding="utf-8") as sail_f:
                        sail_f.write(timestamp + sail_readdata + "\n")
            else:
                sail_timeout_count += sail_timeout_count
                if sail_timeout_count > 500:
                    ser_sail.close()
                    ser_sail = serial.Serial(SAIL_COM_PORT, 115200, timeout=1)
                    timestamp = timestamp_get()
                    testlog_write(TESTLOG_WRITE, '[sail]     :' + timestamp_get() + 'serial通信途絶(500sec).再接続実施' )
                    sail_timeout_count = 0
                
            if not q_sail.empty():
                sail_evid, sail_evdata = q_sail.get()
                if sail_evid == EV_SAIL_SER_WRITE:
                    sail_senddata = list(sail_evdata)
                    sail_senddata.append('\r')
                    for data in sail_senddata:
                        ser_sail.write(data.encode('utf-8'))
                        time.sleep(0.2)
                else:
                    pass
                q_sail.task_done()
        except UnicodeDecodeError as e:
            pass
        except UnicodeEncodeError as e:
            pass
        except serial.SerialException as e:
            if ser_sail.isOpen() == True:
                ser_sail.close()
            testlog_write(TESTLOG_WRITE, '[sail]     :' + timestamp_get() + 'serial通信接続失敗,5秒後に再接続実施' )
            sail_contine_flag = True
            time.sleep(5) 
    if ser_sail.isOpen() == True:
        ser_sail.close()


def ucom_error_monitor(readdata, time):
    global sleep_chk_flg
    global test_task
    
    ucom_error_flg = 0
#    system_ucom_extract(readdata)
#    fcp_extract(readdata)
#    hwvari_extract(readdata)
    
    if 'PMT:Meter Fin End' in readdata:
        sleep_chk_flg = 1
    elif 'PMT:ASEE T.O.' in readdata:
        sleep_chk_flg = 10
        #SAILの特定ログが検出されない状態で、'PMT:ASEE T.O'を検知した場合は停止
        if ASEE_TO_TESTSTOP == 1 and test_task == TASK_SUPEND_WAIT:
            if sail_Interrupt_check1 == 0 or sail_Interrupt_check2 == 0:
                print('"PMT:ASEE T.O"を検知')
                test_task = TASK_STOP
    elif 'PMT:ASEE High' in readdata:
        sleep_chk_flg = 0

    if ucom_error_flg == 1:
        error_data = '[ucom]     :' + time + ' ' + readdata
        testlog_write(TESTLOG_WRITE, error_data)

    for i in range(len(ucom_failsafe_list)):
        if ucom_failsafe_list[i][1] in readdata:
            error_data =f'[ucom]    :{time} {ucom_failsafe_list[i][0]} : {readdata}'
            testlog_write(TESTLOG_WRITE, error_data)
            break


def qnx_error_monitor(readdata, time):
    global test_task
    global test_task_copy
    global ramdump_timeoutcnt

    qnx_error_flg = 0
    if 'devctl(STR) result: 11' in readdata:
        qnx_error_flg = 1
    elif 'devctl(STR) result: 16' in readdata:
        qnx_error_flg = 1
    elif 'devctl(STR) result: 120' in readdata:
        qnx_error_flg = 1
    elif 'devctl(STR) result: -' in readdata:
        qnx_error_flg = 1
    elif 'devctl(STR): retry_cnt:' in readdata:
        qnx_error_flg = 1
    elif 'str_ctrl_retry' in readdata:
        qnx_error_flg = 1
    elif 'dumping to /var/log/' in readdata:
        if '.core' in readdata:
            qnx_error_flg = 1
    elif 'Format: Log Type - Time(microsec)' in readdata:
        if test_task != TASK_INIT:
            qnx_error_flg = 1
            if DUMP_MODE == 2:
                if test_task == TASK_RUMDUMP_WAIT:
                    #RAMdumpの終了判定(RAMDump終了後のリセットタイミング)
                    test_task = TASK_ERROR
            else:
                if test_task != TASK_ERROR:
                    test_task_copy = test_task
                    test_task = TASK_ERROR
    elif 'RamDump -  Image Loaded, Delta' in readdata:
        if test_task != TASK_INIT:
            if DUMP_MODE == 2:
                if test_task != TASK_RUMDUMP_WAIT and test_task != TASK_ERROR:
                    if '(0 Bytes)' in readdata:
                        #RamDumpデータなし
                        test_task_copy = test_task
                        test_task = TASK_ERROR
                    else:
                        #RAMdumpの開始判定
                        qnx_error_flg = 1
                        test_task_copy = test_task
                        ramdump_timeoutcnt = 0
                        test_task = TASK_RUMDUMP_WAIT
    else:
        qnx_error_flg = 0
    if qnx_error_flg == 1:
        error_data = '[qnx]     :' + time + ' ' + readdata
        testlog_write(TESTLOG_WRITE, error_data)

def android_error_monitor(readdata, time):
    global sail_Interrupt_check1
    global sail_Interrupt_check2
    
    android_error_flg = 0
    if 'abnormal_reset' in readdata:
        android_error_flg = 1
    elif 'reboot: Power down' in readdata:
        android_error_flg = 1
    elif 'Interrupt disabled successfully' in readdata:
        if 'prvXBLDeInit_Sleep xSleepDriverAck Success' in readdata:
            sail_Interrupt_check1 = 1
            print(f'"{readdata}"を検知')
        elif 'Ack to MD : 0xAA030000' in readdata:
            sail_Interrupt_check2 = 1
            print(f'"{readdata}"を検知')
    if android_error_flg == 1:
        error_data = '[android] :' + time + ' ' + readdata
        testlog_write(TESTLOG_WRITE, error_data)

def sail_error_monitor(readdata, time):
    sail_error_flg = 0
#    sail_img_id_extract(readdata)
    if sail_error_flg == 1:
        error_data = '[sail]    :' + time + ' ' + readdata
        testlog_write(TESTLOG_WRITE, error_data)

def testlog_write(req, writedata):
    lock5.acquire()
    if req == COUNTLOG_WRITE_INIT:
        lines = []
        lines.append("COUNTLOG:------------------------------------------------------------------\n")
        lines.append("suspend_count:" + str(suspend_count) + "\n")
        lines.append("resume_count:" + str(resume_count) + "\n")
        lines.append("suspend_error_count:" + str(supend_error_count) + "\n")
        lines.append("resume_error_count:" + str(resume_error_count) + "\n")
        lines.append("consecutive_success_count:" + str(consecutive_success_count) + "\n")
        lines.append("consecutive_success_max_count:" + str(consecutive_success_max_count) + "\n")
        lines.append("TESTLOG:-------------------------------------------------------------------\n")
        with open(logfpath + "/testlog.txt", 'w',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    elif req == COUNTLOG_WRITE:
        with open(logfpath + "/testlog.txt", 'r',encoding="utf-8") as test_f:
            lines = test_f.readlines()
        lines[0] = "COUNTLOG:------------------------------------------------------------------\n"
        lines[1] = "suspend_count:" + str(suspend_count) + "\n"
        lines[2] = "resume_count:" + str(resume_count) + "\n"
        lines[3] = "suspend_error_count:" + str(supend_error_count) + "\n"
        lines[4] = "resume_error_count:" + str(resume_error_count) + "\n"
        lines[5] = "consecutive_success_count:" + str(consecutive_success_count) + "\n"
        lines[6] = "consecutive_success_max_count:" + str(consecutive_success_max_count) + "\n"
        lines[7] = "TESTLOG:-------------------------------------------------------------------\n"
        with open(logfpath + "/testlog.txt", 'w',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    elif req == TESTLOG_WRITE:
        with open(logfpath + "/testlog.txt", 'a',encoding="utf-8") as test_f:
            test_f.write(writedata + "\n")
    elif req == TESTLOG_WRITE_INIT:
        index = str(log_index)
        lines = []
        lines.append("---------------------------------------------------------------------------\n")
        lines.append("Log recording start(android_" + index + ".log,qnx_" + index + ".log,sail_" + index + ".log,ucom_" + index + ".log)\n")
        lines.append("---------------------------------------------------------------------------\n")
        with open(logfpath + "/testlog.txt", 'a',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    elif req == TESTLOG_SUS_ERROR:
        lines = []
        if TEST_MODE == 0:
            lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. "I:1:PMT:ASEE High" could not be found.\n')
        elif TEST_MODE == 1:
            lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. ACCOFFから折り返しログ"{suspend_trigger_list[suspend_select_trigger][1]}"が未検知\n')
        elif TEST_MODE == 4:
            if resume_after_trigger[0] != '':
                lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. 折り返しログ"{resume_after_trigger[0]}"検知からACCOFF後、サスペンドログ"PMT:ASEE High"が未検知\n')
            else:
                lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. "I:1:PMT:ASEE High" could not be found.\n')
        lines.append('[tool]    :' + timestamp_get() + ' Log Stop recording.\n')
        lines.append('[tool]    :' + timestamp_get() + ' テスト結果:' + str(consecutive_success_count) + '回連続成功(' + str(consecutive_success_count + 1) + '回目失敗)\n')
        with open(logfpath + "/testlog.txt", 'a',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    elif req == TESTLOG_RES_ERROR:
        lines = []
        if TEST_MODE == 0:
            lines.append(f'[tool]    :{timestamp_get()} Resume Error Detected. "VHM:APSROn" could not be found.\n')
        elif TEST_MODE == 1:
            lines.append(f'[tool]    :{timestamp_get()} Resume Error Detected. 折り返しログ"{suspend_trigger_list[suspend_select_trigger][1]}"検知からACCON後、起動ログ"VHM:APSROn"が未検知\n')
        elif TEST_MODE == 4:
            lines.append(f'[tool]    :{timestamp_get()} Resume Error Detected. ACCONから折り返しログ"{resume_trigger_list[resume_select_trigger][1]}"が未検知\n')
        lines.append('[tool]    :' + timestamp_get() + ' Log Stop recording.\n')
        lines.append('[tool]    :' + timestamp_get() + ' テスト結果:' + str(consecutive_success_count) + '回連続成功(' + str(consecutive_success_count + 1) + '回目失敗)\n')
        with open(logfpath + "/testlog.txt", 'a',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    elif req == TESTLOG_RESET_SUS_ERROR:
        lines = []
        if TEST_MODE == 0 or TEST_MODE >= 4:
            lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. A reset occurred while Suspend was in progress.\n')
        elif TEST_MODE == 1:
            lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. ACCOFFから折り返しログ"{suspend_trigger_list[suspend_select_trigger][1]}"待機中にリセット検知\n')
        elif TEST_MODE == 2 or TEST_MODE == 3:
            lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. ACCOFFから折り返し時間{suspend_time}秒経過を待機中にリセット検知\n')
        elif TEST_MODE == 4:
            if resume_after_trigger[0] != '':
                lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. 折り返しログ"{resume_after_trigger[0]}"検知からACCOFF後、サスペンドログ"PMT:ASEE High"を待機中にリセット検知\n')
            else:
                lines.append(f'[tool]    :{timestamp_get()} Suspend Error Detected. A reset occurred while Suspend was in progress.\n')
        lines.append('[tool]    :' + timestamp_get() + ' Log Stop recording.\n')
        lines.append('[tool]    :' + timestamp_get() + ' テスト結果:' + str(consecutive_success_count) + '回連続成功(' + str(consecutive_success_count + 1) + '回目失敗)\n')
        with open(logfpath + "/testlog.txt", 'a',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    elif req == TESTLOG_RESET_RES_ERROR:
        lines = []
        if TEST_MODE == 0:
            lines.append(f'[tool]    :{timestamp_get()} Resume Error Detected. A reset occurred while Resume was in progress.\n')
        elif TEST_MODE == 1:
            lines.append(f'[tool]    :{timestamp_get()} Resume Error Detected. 折り返しログ"{suspend_trigger_list[suspend_select_trigger][1]}"検知からACCON後、起動ログ"VHM:APSROn"を待機中にリセット検知\n')
        elif TEST_MODE == 2 or TEST_MODE == 3:
            lines.append(f'[tool]    :{timestamp_get()} Resume Error Detected. 折り返し時間{suspend_time}秒経過からACCON後、起動ログ"VHM:APSROn"を待機中にリセット検知\n')
        elif TEST_MODE == 4:
            lines.append(f'[tool]    :{timestamp_get()} Resume Error Detected. ACCONから折り返しログ"{resume_trigger_list[resume_select_trigger][1]}"待機中にリセット検知\n')
        elif TEST_MODE == 5 or TEST_MODE == 6:
            lines.append(f'[tool]    :{timestamp_get()} Resume Error Detected. ACCONから折り返し時間{resume_time}秒経過を待機中にリセット検知\n')
        lines.append('[tool]    :' + timestamp_get() + ' Log Stop recording.\n')
        lines.append('[tool]    :' + timestamp_get() + ' テスト結果:' + str(consecutive_success_count) + '回連続成功(' + str(consecutive_success_count + 1) + '回目失敗)\n')
        with open(logfpath + "/testlog.txt", 'a',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    elif req == TESTLOG_CHG:
        lines = []
        lines.append('[tool]    :' + timestamp_get() + ' テストの連続成功回数がLog保存の閾値を超えたため、Logの切り替えを行います.\n')
        lines.append('[tool]    :' + timestamp_get() + ' Log Stop recording.\n')
        lines.append('[tool]    :' + timestamp_get() + ' テスト結果:' + str(consecutive_success_count) + '回連続成功中\n')
        with open(logfpath + "/testlog.txt", 'a',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    elif req == TESTLOG_END:
        lines = []
        lines.append('[tool]    :' + timestamp_get() + ' Log Stop recording.\n')
        lines.append('[tool]    :' + timestamp_get() + ' テスト結果:' + str(consecutive_success_count) + '回連続成功\n')
        with open(logfpath + "/testlog.txt", 'a',encoding="utf-8") as test_f:
            test_f.writelines(lines)
    lock5.release()

def camera_control():
    global q_camera
    global tool_state

    cap = cv2.VideoCapture(CAMERA_ID,cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_SETTINGS, 1)
    cv2.namedWindow('camera window', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('camera window', 640, 360)
    cv2.moveWindow('camera window', 1210, 200)
    while tool_state == TOOL_STATE_RUN:
        if cv2.getWindowProperty('camera window', cv2.WND_PROP_VISIBLE) < 1:
            tool_state = TOOL_STATE_END
            break
        ret, frame = cap.read()
        if ret:
            resized_frame = cv2.resize(frame, (640, 360))
            cv2.imshow('camera window', resized_frame)  # ウィンドウ名とフレームを表示
            cv2.waitKey(1)
            if not q_camera.empty():
                if TEST_MODE == 0:
                    add_test_index = ''
                elif TEST_MODE == 1:
                    add_test_index = f'_({suspend_trigger_list[suspend_select_trigger][4]})'
                elif TEST_MODE == 2 or TEST_MODE == 3:
                    add_test_index = f'_(wait_{suspend_time}_sec)'
                elif TEST_MODE == 4:
                    add_test_index = f'_({resume_trigger_list[resume_select_trigger][4]})'
                elif TEST_MODE == 5 or TEST_MODE == 6:
                    add_test_index = f'_(wait_{resume_time}_sec)'
                else:
                    add_test_index = ''
                camera_event = q_camera.get()
                if camera_event == EV_CAMERA_SS_SUSPEND:
                    if TEST_MODE == 4:
                        if resume_after_trigger[1] != '':
                             add_test_index = f'_({resume_after_trigger[1]})'
                        else:
                            add_test_index = ''
                    ssfolder = fr'{logfpath}/SS_{str(log_index)}'
                    os.makedirs(ssfolder, exist_ok=True)
                    filename = fr'{datastr_get()}_suspend_{str(suspend_count)}{add_test_index}.jpg'
                    cv2.imwrite(filename, frame)
                    file_move(filename,fr'{ssfolder}/{filename}')
                elif camera_event == EV_CAMERA_SS_RESUME:
                    ssfolder = fr'{logfpath}/SS_{str(log_index)}'
                    os.makedirs(ssfolder, exist_ok=True)
                    filename = fr'{datastr_get()}_resume_{str(resume_count)}{add_test_index}.jpg'
                    cv2.imwrite(filename, frame)
                    file_move(filename,fr'{ssfolder}/{filename}')
                elif camera_event == EV_CAMERA_SS_SUS_ERR:
                    if TEST_MODE == 4:
                        if resume_after_trigger[1] != '':
                             add_test_index = f'_({resume_after_trigger[1]})'
                        else:
                            add_test_index = ''
                    ssfolder = fr'{logfpath}/SS_{str(log_index)}'
                    os.makedirs(ssfolder, exist_ok=True)
                    filename = fr'{datastr_get()}_suspend_error_{str(supend_error_count)}{add_test_index}.jpg'
                    cv2.imwrite(filename, frame)
                    file_move(filename,fr'{ssfolder}/{filename}')
                elif camera_event == EV_CAMERA_SS_RES_ERR:
                    ssfolder = fr'{logfpath}/SS_{str(log_index)}'
                    os.makedirs(ssfolder, exist_ok=True)
                    filename = fr'{datastr_get()}_resume_error_{str(resume_error_count)}{add_test_index}.jpg'
                    cv2.imwrite(filename, frame)
                    file_move(filename,fr'{ssfolder}/{filename}')
                else:
                    pass
                q_camera.task_done()
    cap.release()
    cv2.destroyAllWindows()

def file_move(source,destination):
    
    result = RESULT_NG
    
    try:
        if source != None and destination != None:
            # ファイルを移動
            shutil.move(source, destination)
            result = RESULT_OK
    except FileNotFoundError:
        print("指定されたファイルが見つかりませんでした。")
    except PermissionError:
        print("権限が不足しています。")
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        
    return result
    
def func_wait(timedata):
    
    result = RESULT_OK
    for i in range(0, timedata, 1):
        time.sleep(1)
        if tool_state != TOOL_STATE_RUN:
            result = RESULT_NG
            break
        if test_task == TASK_ERROR or test_task == TASK_STOP:
            break
    return result

def consol_log_label(str_data):

    timestamp = timestamp_get()

    with open(logfpath + '/ucom_' + str(log_index) + '.log', 'a',encoding="utf-8") as f:
        f.write(f'#################### {timestamp} {str_data} ####################\n')

    with open(logfpath + '/qnx_' + str(log_index) + '.log', 'a',encoding="utf-8") as f:
        f.write(f'#################### {timestamp} {str_data} ####################\n')

    with open(logfpath + '/android_' + str(log_index) + '.log', 'a',encoding="utf-8") as f:
        f.write(f'#################### {timestamp} {str_data} ####################\n')

    with open(logfpath + '/sail_' + str(log_index) + '.log', 'a',encoding="utf-8") as f:
        f.write(f'#################### {timestamp} {str_data} ####################\n')

def func_susres_test():
    global suspend_wait_flag
    global resume_wait_flag
    global log_index
    global suspend_count
    global resume_count
    global supend_error_count
    global resume_error_count
    global consecutive_success_count
    global consecutive_success_max_count
    global test_task
    global test_task_copy
    global ramdump_timeoutcnt
    global suspend_select_trigger
    global suspend_time
    global resume_select_trigger
    global resume_time
    global sleep_chk_flg
    global sail_Interrupt_check1
    global sail_Interrupt_check2
    global resume_after_trigger
    global tool_state
    global log_max_count
    
    time.sleep(5)
    testlog_write(COUNTLOG_WRITE_INIT,'')
    susres_test_info(into_info='試験開始')
    while tool_state == TOOL_STATE_RUN:
        if  test_task == TASK_INIT:
            sleep_chk_flg = 0
            log_max_count = TESTLOG_MAX_COUNT
            resume_after_trigger = ['','']
            senddata='slog2info'
            q_qnx.put((EV_QNX_SER_WRITE, senddata))
            q_qnx.join()
            if TEST_MODE == 1:
                suspend_select_trigger += 1
                for i in range (0,len(suspend_trigger_list)):
                    if suspend_select_trigger >= len(suspend_trigger_list):
                        suspend_select_trigger = 0
                    if suspend_trigger_list[suspend_select_trigger][5] == True:
                        break
                    else:
                        suspend_select_trigger += 1
            elif TEST_MODE == 4:
                resume_select_trigger += 1
                for i in range (0,len(resume_trigger_list),1):
                    if resume_select_trigger >= len(resume_trigger_list):
                        resume_select_trigger = 0
                    if resume_trigger_list[resume_select_trigger][5] == True:
                        break
                    else:
                        resume_select_trigger += 1
            testlog_write(COUNTLOG_WRITE,'')
            testlog_write(TESTLOG_WRITE_INIT,'')
            pika_start()
            result = func_wait(3)
            if  result == RESULT_NG:
                break
            senddata = 'MCU_DEBUG0401130101010101'
            for i in range(0,3,1):
                q_ucom.put((EV_UCOM_SER_WRITE, senddata))
                q_ucom.join()
                time.sleep(0.1)
            senddata = 'MCU_DEBUG04041201'
            for i in range(0,3,1):
                q_ucom.put((EV_UCOM_SER_WRITE, senddata))
                q_ucom.join()
                time.sleep(0.1)
            senddata = 'MCU_DEBUG0901'
            for i in range(0,3,1):
                q_ucom.put((EV_UCOM_SER_WRITE, senddata))
                q_ucom.join()
                time.sleep(0.1)
            result = func_wait(30)
            if  result == RESULT_NG:
                break
            if SAIL_DEBUG_MODE_DISABLE == 1:
                senddata = 'testapp  -e 0'
                q_qnx.put((EV_QNX_SER_WRITE, senddata))
                q_qnx.join()
                result = func_wait(1)
            if DUMP_MODE == 2:
                #fulldumpに設定
                senddata = 'echo full > /dev/pdbg/memorydump/dload/dload_mode'
                q_qnx.put((EV_QNX_SER_WRITE, senddata))
                q_qnx.join()
                result = func_wait(1)
                #フェールセーフリセット解除
                senddata = 'MCU_DEBUG2601'
                q_ucom.put((EV_UCOM_SER_WRITE, senddata))
                q_ucom.join()
                result = func_wait(1)
                senddata = 'MCU_DEBUG2602'
                q_ucom.put((EV_UCOM_SER_WRITE, senddata))
                q_ucom.join()
                result = func_wait(1)
            if DUMP_MODE == 1:
                senddata = 'echo 1 > /dev/pdbg/pm/power/lpm/debug_mode'
                q_qnx.put((EV_QNX_SER_WRITE, senddata))
                q_qnx.join()
                result = func_wait(1)
            if DUMP_MODE == 1:
                senddata = 'cat /dev/pdbg/pm/power/lpm/debug_mode'
                q_qnx.put((EV_QNX_SER_WRITE, senddata))
                q_qnx.join()
                result = func_wait(1)
            if ADD_SAILLOG_ON == 1:
                senddata = 'saildbg -w /dev/sail/tst0 -c 0x29 -l 0x0E -p 0x73 0x65 0x74 0x6c 0x6f 0x67 0x69 0x6e 0x66 0x6f 0x5f 0x65 0x6c 0x31'
                q_qnx.put((EV_QNX_SER_WRITE, senddata))
                q_qnx.join()
                result = func_wait(5)
            if ADD_SAILLOG_ON == 1:
                senddata = 'setloginfo_el2'
                q_sail.put((EV_SAIL_SER_WRITE, senddata))
                q_sail.join()
                
                result = func_wait(3)
                
                senddata = 'setloginfo_el1'
                q_sail.put((EV_SAIL_SER_WRITE, senddata))
                q_sail.join()
                result = func_wait(1)
            if TOOL_MODE == 0:
                senddata = '/vendor/bin/candy-test-ivehicle set 557924608 0 int32Values 0 0 0 0'
                q_android.put((EV_ANDROID_SER_WRITE, senddata))
                q_android.join()
            result = func_wait(10)
            if  result == RESULT_NG:
                break
            if ANDROID_LOGCAT_ENABLE == 1:
                senddata = 'logcat -c'
                q_android.put((EV_ANDROID_SER_WRITE, senddata))
                q_android.join()
                result = func_wait(5)
                if  result == RESULT_NG:
                    break
                senddata = 'logcat &'
                q_android.put((EV_ANDROID_SER_WRITE, senddata))
                q_android.join()
                result = func_wait(15)
                if  result == RESULT_NG:
                    break
            accoff_reason = None
            test_task = TASK_SUPEND
        elif test_task == TASK_SUPEND:
            senddata='slog2info'
            q_qnx.put((EV_QNX_SER_WRITE, senddata))
            q_qnx.join()
            pika_stop(accoff_reason)
            suspend_wait_flag = 1
            sail_Interrupt_check1 = 0
            sail_Interrupt_check2 = 0
            accoff_start_time = int(time.time())
            if TOOL_MODE == 0:
                senddata = '/vendor/bin/candy-test-ivehicle set 557924608 0 int32Values 1 0 0 0'
                q_android.put((EV_ANDROID_SER_WRITE, senddata))
                q_android.join()
            if test_task == TASK_SUPEND:
                test_task = TASK_SUPEND_WAIT
                if TEST_MODE == 2:
                    suspend_time = ACC_OFFON_TIME
                elif TEST_MODE == 3:
                    if ACC_OFFON_RANDUM_MIN < ACC_OFFON_RANDUM_MAX:
                        suspend_time = random.randint(ACC_OFFON_RANDUM_MIN, ACC_OFFON_RANDUM_MAX)
                    elif ACC_OFFON_RANDUM_MIN > ACC_OFFON_RANDUM_MAX:
                        suspend_time = random.randint(ACC_OFFON_RANDUM_MAX, ACC_OFFON_RANDUM_MIN)
                    else:
                        suspend_time = ACC_OFFON_RANDUM_MIN
                    
        elif test_task == TASK_SUPEND_WAIT:
            if SLEEP_CHECK == 1:
                if sleep_chk_flg == 1:
                    meterfintime = time.time()
                    sleep_chk_flg = 2
                elif sleep_chk_flg == 2:
                    timecnt = int(meterfintime - time.time())
                    if timecnt > 20:
                        #QNXにコマンド送信
                        q_qnx.put((EV_QNX_SER_WRITE, 'env'))
                        sleep_chk_flg = 0
                elif sleep_chk_flg == 10:
                    #uComにコマンド送信
                    q_ucom.put((EV_UCOM_SER_WRITE, 'MCU_DEBUG12024'))
                    sleep_chk_flg = 0
            
            if TEST_MODE == 0 or TEST_MODE == 1 or TEST_MODE >= 4:
                if suspend_wait_flag == 1:
                    elapsed_time = int(time.time() - accoff_start_time)
                    if elapsed_time > 300:
                        testlog_write(TESTLOG_SUS_ERROR, "")
                        test_task = TASK_INIT
                        test_task_copy = TASK_NONE
                        supend_error_count += 1
                        consecutive_success_count = 0
                        if CAMERA_ENABLE == True:
                            q_camera.put(EV_CAMERA_SS_SUS_ERR)
                            q_camera.join()
                        log_index += 1
                        susres_test_info(into_info='エラー検知')
                        if test_stop_flag == True:
                            tool_state = TOOL_STATE_END

                else:
                    if TEST_MODE == 0 or TEST_MODE >= 4:
                        result = func_wait(5)
                        accon_reason = ''
                    elif TEST_MODE == 1:
                        accon_reason = f'Detection of log "{suspend_trigger_list[suspend_select_trigger][1]}"'
                    if test_task == TASK_SUPEND_WAIT:
                        suspend_count += 1
                        testlog_write(COUNTLOG_WRITE,'')
                        if CAMERA_ENABLE == True:
                            q_camera.put(EV_CAMERA_SS_SUSPEND)
                            q_camera.join()
                        if test_task == TASK_SUPEND_WAIT:
                            test_task = TASK_RESUME
            elif TEST_MODE == 2 or TEST_MODE == 3:
                elapsed_time = int(time.time() - accoff_start_time)
                if elapsed_time > suspend_time:
                    accon_reason = f'{elapsed_time} seconds after Acc Off'
                    suspend_count += 1
                    testlog_write(COUNTLOG_WRITE,'')
                    if CAMERA_ENABLE == True:
                        q_camera.put(EV_CAMERA_SS_SUSPEND)
                        q_camera.join()
                    if test_task == TASK_SUPEND_WAIT:
                        test_task = TASK_RESUME

        elif test_task == TASK_RESUME:
            resume_wait_flag = 1
            if TEST_MODE == 0 or TEST_MODE >= 4:
                pika_restart()
            else:
                pika_restart(accon_reason)
            wait_count = 0
            sleep_chk_flg = 0
            accon_start_time = int(time.time())
            if TEST_MODE >= 4:
                if TEST_MODE == 5:
                    resume_time = ACC_OFFON_TIME
                elif TEST_MODE == 6:
                    if ACC_OFFON_RANDUM_MIN < ACC_OFFON_RANDUM_MAX:
                        resume_time = random.randint(ACC_OFFON_RANDUM_MIN, ACC_OFFON_RANDUM_MAX)
                    elif ACC_OFFON_RANDUM_MIN > ACC_OFFON_RANDUM_MAX:
                        resume_time = random.randint(ACC_OFFON_RANDUM_MAX, ACC_OFFON_RANDUM_MIN)
                    else:
                        resume_time = ACC_OFFON_RANDUM_MIN
                if TOOL_MODE == 0:
                    senddata = '/vendor/bin/candy-test-ivehicle set 557924608 0 int32Values 0 0 0 0'
                    q_android.put((EV_ANDROID_SER_WRITE, senddata))
                    q_android.join()
                test_task = TASK_RESUME_WAIT
            else:
                result = func_wait(5)
                if  result == RESULT_NG:
                    break
                if test_task == TASK_RESUME:
                    if TOOL_MODE == 0:
                        senddata = '/vendor/bin/candy-test-ivehicle set 557924608 0 int32Values 0 0 0 0'
                        q_android.put((EV_ANDROID_SER_WRITE, senddata))
                        q_android.join()
                    if SAIL_DEBUG_MODE_DISABLE == 1:
                        senddata = 'testapp  -e 0'
                        q_qnx.put((EV_QNX_SER_WRITE, senddata))
                        q_qnx.join()
                        result = func_wait(1)
                    if DUMP_MODE == 2:
                        #フェールセーフリセット解除
                        senddata = 'MCU_DEBUG2601'
                        q_ucom.put((EV_UCOM_SER_WRITE, senddata))
                        q_ucom.join()
                        result = func_wait(1)
                        senddata = 'MCU_DEBUG2602'
                        q_ucom.put((EV_UCOM_SER_WRITE, senddata))
                        q_ucom.join()
                        result = func_wait(1)
                    if DUMP_MODE == 1:
                        senddata = 'echo 1 > /dev/pdbg/pm/power/lpm/debug_mode'
                        q_qnx.put((EV_QNX_SER_WRITE, senddata))
                        q_qnx.join()
                        result = func_wait(1)
                    if DUMP_MODE == 1:
                        senddata = 'cat /dev/pdbg/pm/power/lpm/debug_mode'
                        q_qnx.put((EV_QNX_SER_WRITE, senddata))
                        q_qnx.join()
                        result = func_wait(1)
                    if ADD_SAILLOG_ON == 1:
                        senddata = 'saildbg -w /dev/sail/tst0 -c 0x29 -l 0x0E -p 0x73 0x65 0x74 0x6c 0x6f 0x67 0x69 0x6e 0x66 0x6f 0x5f 0x65 0x6c 0x31'
                        q_qnx.put((EV_QNX_SER_WRITE, senddata))
                        q_qnx.join()
                        result = func_wait(5)
                    if ADD_SAILLOG_ON == 1:
                        for i in range(0,3,1):
                            senddata = 'setloginfo_el2'
                            q_sail.put((EV_SAIL_SER_WRITE, senddata))
                            q_sail.join()
                            time.sleep(0.3)

                            result = func_wait(1)

                            senddata = ''
                            q_sail.put((EV_SAIL_SER_WRITE, senddata))
                            q_sail.join()
                            time.sleep(0.3)

                            result = func_wait(1)

                            senddata = 'setloginfo_el1'
                            q_sail.put((EV_SAIL_SER_WRITE, senddata))
                            q_sail.join()
                            time.sleep(0.3)

                            result = func_wait(1)
                    
                    #PJ11DEF00-11182確認用の追加箇所
                    senddata = 'showmem'
                    q_qnx.put((EV_QNX_SER_WRITE, senddata))
                    q_qnx.join()
                    
                    if test_task == TASK_RESUME:
                        test_task = TASK_RESUME_WAIT

        elif test_task == TASK_RESUME_WAIT:
            if TEST_MODE <= 4:
                if resume_wait_flag == 1:
                    elapsed_time = int(time.time() - accon_start_time)
                    if elapsed_time > 180:
                        testlog_write(TESTLOG_RES_ERROR, "")
                        test_task = TASK_INIT
                        test_task_copy = TASK_NONE
                        resume_error_count += 1
                        consecutive_success_count = 0
                        if ADB_SS_ENABLE == 1:
                            if TEST_MODE == 0:
                                add_test_index = ''
                            elif TEST_MODE == 1:
                                add_test_index = f'_({suspend_trigger_list[suspend_select_trigger][4]})'
                            elif TEST_MODE == 2 or TEST_MODE == 3:
                                add_test_index = f'_(wait_{suspend_time}_sec)'
                            elif TEST_MODE == 4:
                                add_test_index = f'_(wait_{resume_time}_sec)'
                            filename = f'resume_error_{str(resume_error_count)}{add_test_index}.png'
                            adb_screenshot(filename)
                        if CAMERA_ENABLE == True:
                            q_camera.put(EV_CAMERA_SS_RES_ERR)
                            q_camera.join()
                        log_index += 1
                        susres_test_info(into_info='エラー検知')
                        if test_stop_flag == True:
                            tool_state = TOOL_STATE_END
                else:
                    if TEST_MODE == 4:
                        accoff_reason = f'Detection of log "{resume_trigger_list[resume_select_trigger][1]}"'
                        resume_after_trigger[0] = resume_trigger_list[resume_select_trigger][1]
                        resume_after_trigger[1] = resume_trigger_list[resume_select_trigger][4]
                    else:
                        accoff_reason = None
                        result = func_wait(20)
                        if  result == RESULT_NG:
                            break
                    if test_task == TASK_RESUME_WAIT:
                        resume_count += 1
                        consecutive_success_count += 1
                        
                        if consecutive_success_count > consecutive_success_max_count:
                            consecutive_success_max_count = consecutive_success_count
                            
                        testlog_write(COUNTLOG_WRITE,'')
                        
                        if ADB_SS_ENABLE == 1:
                            if TEST_MODE == 0:
                                add_test_index = ''
                            elif TEST_MODE == 1:
                                add_test_index = f'_({suspend_trigger_list[suspend_select_trigger][4]})'
                            elif TEST_MODE == 2 or TEST_MODE == 3:
                                add_test_index = f'_(wait_{suspend_time}_sec)'
                            elif TEST_MODE == 4:
                                add_test_index = f'_(wait_{resume_time}_sec)'
                            filename = f'resume_{str(resume_count)}{add_test_index}.png'
                            adb_screenshot(filename)
                        if CAMERA_ENABLE == True:
                            q_camera.put(EV_CAMERA_SS_RESUME)
                            q_camera.join()
                        
                        if TEST_MODE == 1:
                            suspend_select_trigger += 1
                            for i in range (0,len(suspend_trigger_list),1):
                                if suspend_select_trigger >= len(suspend_trigger_list):
                                    suspend_select_trigger = 0
                                if suspend_trigger_list[suspend_select_trigger][5] == True:
                                    break
                                else:
                                    suspend_select_trigger += 1
                        elif TEST_MODE == 4:
                            resume_select_trigger += 1
                            for i in range (0,len(resume_trigger_list),1):
                                if resume_select_trigger >= len(resume_trigger_list):
                                    resume_select_trigger = 0
                                if resume_trigger_list[resume_select_trigger][5] == True:
                                    break
                                else:
                                    resume_select_trigger += 1
                        log_index_chek()
                        if test_task == TASK_RESUME_WAIT:
                            test_task = TASK_SUPEND
                            if test_stop_flag == True:
                                tool_state = TOOL_STATE_END
            elif TEST_MODE == 5 or TEST_MODE == 6:
                elapsed_time = int(time.time() - accoff_start_time) 
                if elapsed_time > resume_time:
                    accoff_reason = f'{elapsed_time} seconds after Acc On'
                    resume_count += 1
                    consecutive_success_count += 1
                    
                    testlog_write(COUNTLOG_WRITE,'')
                    
                    if consecutive_success_count > consecutive_success_max_count:
                        consecutive_success_max_count = consecutive_success_count
                    if ADB_SS_ENABLE == 1:
                        add_test_index = f'_(wait_{resume_time}_sec)'
                        filename = f'resume_{str(resume_count)}{add_test_index}.png'
                        adb_screenshot(filename)
                    if CAMERA_ENABLE == True:
                        q_camera.put(EV_CAMERA_SS_RESUME)
                        q_camera.join()
                    log_index_chek()
                    if test_task == TASK_RESUME_WAIT:
                        test_task = TASK_SUPEND
                        if test_stop_flag == True:
                            tool_state = TOOL_STATE_END
        elif test_task == TASK_ERROR:
            
            # サスペンド動作中にリセットを検知した場合
            if test_task_copy == TASK_SUPEND or test_task_copy == TASK_SUPEND_WAIT:
                testlog_write(TESTLOG_RESET_SUS_ERROR, "")
                supend_error_count += 1
                consecutive_success_count = 0
                if CAMERA_ENABLE == True:
                    q_camera.put(EV_CAMERA_SS_SUS_ERR)
                    q_camera.join()
            # レジューム動作中にリセットを検知した場合
            elif test_task_copy == TASK_RESUME or test_task_copy == TASK_RESUME_WAIT:
                testlog_write(TESTLOG_RESET_RES_ERROR, "")
                resume_error_count += 1
                consecutive_success_count = 0
                if CAMERA_ENABLE == True:
                    q_camera.put(EV_CAMERA_SS_RES_ERR)
                    q_camera.join()
            else:
                pass
            
            # 10秒間待機。エラー時のログ収集のため。
            for i in range(0, 10, 1):
                time.sleep(1)
                if tool_state != TOOL_STATE_RUN:
                    break
            
            log_index += 1
            susres_test_info(into_info='エラー検知')
            test_task = TASK_INIT
            test_task_copy = TASK_NONE
            if test_stop_flag == True:
                tool_state = TOOL_STATE_END

        elif test_task == TASK_RUMDUMP_WAIT:
            # 12000/100ms = 1200秒(20分)経過で強制タイムアウト
            if ramdump_timeoutcnt >= 12000:
                ramdump_timeoutcnt = 0
                test_task = TASK_ERROR
            else:
                if ramdump_timeoutcnt == 0:
                    pika_restart('To get the dump')
                ramdump_timeoutcnt += 1

        elif test_task == TASK_STOP:
            #一度入ったらシリアルログ通信以外の動作を行わない
            print('テスト停止、ログは継続')
            while tool_state == TOOL_STATE_RUN:
                time.sleep(1)
                if test_stop_flag == True:
                    break
            if test_stop_flag == True:
                tool_state = TOOL_STATE_END

        time.sleep(0.1)
    
    testlog_write(COUNTLOG_WRITE,'')
    testlog_write(TESTLOG_END,'')

def log_index_chek():
    global log_index
    global log_max_count
    
    if consecutive_success_count >= log_max_count:
        log_index += 1
        susres_test_info(into_info=f'{consecutive_success_count}回連続成功')
        log_max_count += TESTLOG_MAX_COUNT
        testlog_write(TESTLOG_CHG,'')
        testlog_write(TESTLOG_WRITE_INIT,'')

def pika_init():

    for i in range(0,3,1):
        batt_off()
        acc_off()
        chg_off()
        ill_off()
        bark_off()
        park_off()
#        vsp_off()

def pika_start():

    consol_log_label('pikapati +B OFF / ACC OFF')
    for i in range(0,3,1):
        batt_off()
        acc_off()
        chg_off()
        ill_off()
        bark_off()
        park_off()
#        vsp_off()

    time.sleep(2)
    
    consol_log_label('pikapati +B ON / ACC ON  ')
    for i in range(0,3,1):
        batt_on()
        acc_on()
        chg_on()
#        vsp_on()


def pika_stop(reason=None):

    if reason == None:
        consol_log_label(f'pikapati ACC OFF ')
    else:
        consol_log_label(f'pikapati ACC OFF (reason : {reason})')
    for i in range(0,3,1):
        acc_off()
        chg_off()
    

def pika_restart(reason=None):

    if reason == None:
        consol_log_label(f'pikapati ACC ON ')
    else:
        consol_log_label(f'pikapati ACC ON (reason : {reason})')
    for i in range(0,3,1):
        acc_on()
        chg_on()

def batt_on():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # BATT_ON
    time.sleep(0.01)
    pika_ser.write(b'a')
    pika_ser.read_all()

    pika_ser.close()


def batt_off():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # BATT_OFF
    time.sleep(0.01)
    pika_ser.write(b'b')
    pika_ser.read_all()

    pika_ser.close()


def acc_on():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'c')
    pika_ser.read_all()

    pika_ser.close()


def acc_off():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_OFF
    time.sleep(0.01)
    pika_ser.write(b'd')
    pika_ser.read_all()

    time.sleep(0.01)

    pika_ser.close()


def chg_on():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'e')
    pika_ser.read_all()

    pika_ser.close()
  
def chg_off():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'f')
    pika_ser.read_all()

    pika_ser.close()


def ill_on():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'g')
    pika_ser.read_all()

    pika_ser.close()
  
def ill_off():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'h')
    pika_ser.read_all()

    pika_ser.close()


def bark_on():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'i')
    pika_ser.read_all()

    pika_ser.close()
  
def bark_off():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'j')
    pika_ser.read_all()

    pika_ser.close()


def park_on():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)

    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()

    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'k')
    pika_ser.read_all()

    pika_ser.close()

def park_off():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)
    
    # SW Control NORMAL
    pika_ser.write(b'1')
    pika_ser.read_all()
    
    # ACC_ON
    time.sleep(0.01)
    pika_ser.write(b'l')
    pika_ser.read_all()
    
    pika_ser.close()

def vsp_on():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)
    
    # SW Control PULSE_ON
    pika_ser.write(b'2')
    pika_ser.read_all()
    
    # VSP_ON
    time.sleep(0.02)
    pika_ser.write(b'00')
    pika_ser.read_all()
    
    pika_ser.close()

def vsp_off():
    pika_ser = serial.Serial(PIKA_COM_PORT, 38400 , parity=serial.PARITY_NONE)
    
    # SW Control PULSE_OFF
    pika_ser.write(b'3')
    pika_ser.read_all()
    
    # VSP_OFF
    time.sleep(0.02)
    pika_ser.write(b'00')
    pika_ser.read_all()
    
    pika_ser.close()


def build_number_extract():
    global build_number
    
    if build_number == '-':
        #androidにadb接続の前処理を実行
        senddata1 = 'su'
        senddata2 = 'setprop vendor.sys.usb.adb.disabled 0'
        senddata3 = 'echo "peripheral" > /sys/devices/platform/soc/a600000.ssusb/mode'
        q_android.put((EV_ANDROID_SER_WRITE, senddata1))
        q_android.put((EV_ANDROID_SER_WRITE, senddata2))
        q_android.put((EV_ANDROID_SER_WRITE, senddata3))
        q_android.join()
        
        time.sleep(5)
        
        #adbでスクリーンショットを取得
        cmdlist = ['adb', 'shell', 'getprop', 'ro.build.description']
        result, resmsg = consol_cmd(cmdlist, 5)
        if result == RESULT_OK:
            if 'no devices' not in resmsg:
                build_number = resmsg
                print(f'Build Number : {build_number}')
        
        #androidにadb接続の解除を実行
        senddata1 = 'su'
        senddata2 = 'setprop vendor.sys.usb.adb.disabled 1'
        senddata3 = 'echo "normal" > /sys/devices/platform/soc/a600000.ssusb/mode'
        q_android.put((EV_ANDROID_SER_WRITE, senddata1))
        q_android.put((EV_ANDROID_SER_WRITE, senddata2))
        q_android.put((EV_ANDROID_SER_WRITE, senddata3))
        q_android.join()


def system_ucom_extract(string_data):
    global system_ucom
    
    if system_ucom == '-':
        #etc)I:2:BTM:Sys:**.**.****
        target = 'I:2:BTM:Sys:'
        if target in string_data:
            idx = string_data.find(target)
            system_ucom = string_data[idx+len(target):]
            print(f'System uCOM : {system_ucom}')

def sail_img_id_extract(string_data):
    global sail_img_id
    
    if sail_img_id == '-':
        #etc)SAIL image id: SAIL.SI.1.0.r3-00007-AU.LEMANS-1.100974.2
        target = 'SAIL image id: '
        if target in string_data:
            idx = string_data.find(target)
            sail_img_id = string_data[idx+len(target):]
            print(f'SAIL Image ID : {sail_img_id}')

def fcp_extract(string_data):
    global fcp
    
    if fcp == '-':
        #etc)I:2:FCP:R:VC=0x334d414130.00
        target = 'I:2:FCP:R:VC=0x'
        if target in string_data:
            idx = string_data.find(target)
            hex_string = string_data[idx+len(target):-3]
            fcp = bytes.fromhex(hex_string).decode('ascii')
            print(f'FCP : {fcp}')

def hwvari_extract(string_data):
    global hw_vari
    global wk_ev
    
    if hw_vari == '-' or wk_ev == '-':
    
        wklist_da = [
            ['0WK','01'],
            ['1WK','02'],
            ['2WK','03'],
            ['3WK','04'],
            ['4WK','05'],
            ['5WK','06'],
            ['PP1','10'],
            ['PP2','11'],
            ['PP3','12'],
            ['PP4','13'],
            ['PP5','14'],
            ['AP' ,'20'],
            ['MP' ,'30']
        ]
        
        #etc)I:2:FCP:R:HV=A8,0x02,0x04
        target = 'I:2:FCP:R:HV='
        length = len(target)
        if target in string_data:
            idx = string_data.find(target)
            idx2 = string_data.find(',')
            idx3 = string_data.rfind(',')
            hw_vari = string_data[idx+length:idx2]
            wk_index = string_data[idx3+3:idx3+5]
            for i in range(len(wklist_da)):
                if wklist_da[i][1] == wk_index:
                    wk_ev = wklist_da[i][0]
            print(f'HWバリ : {hw_vari}')
            print(f'WK_index : {wk_index}')
            print(f'WK : {wk_ev}')

def send_message(url, msg):
    # POSTリクエストを送信
    response = requests.post(
        url=url,
        data=json.dumps(msg),
        headers={"Content-Type": "application/json"}
    )
    return response

def susres_test_info(into_url=None,into_title=None,into_info='-'):
    
    if into_url == None:
        url = TEAMS_URL
    else:
        url = into_url
    
    if into_title == None:
        title = TEAMS_TITLE
    else:
        title = into_title
    
    if TEAMS_ENABLE == 1:
        text = (
    #             "試験環境\n"
    #            f"* SoC : {build_number}\n"
    #            f"* System_uCom : {system_ucom}\n"
    #            f"* SAIL : {sail_img_id}\n"
    #            f"* FCP : {fcp}\n"
    #            f"* HWバリ : {hw_vari}\n"
    #            f"* WK : {wk_ev}\n"
    #            "\n"
                "試験状況\n"
                f"* 通知種別：{into_info} \n"
                f"* サスペンド回数 : {suspend_count} / レジューム回数 : {resume_count} \n"
                f"* サスペンドエラー回数 : {supend_error_count} \n"
                f"* レジュームエラー回数 : {resume_error_count} \n"
                f"* 連続成功回数 : {consecutive_success_count} \n"
                f"* 最大連続成功回数 : {consecutive_success_max_count}"
        )
        #################################
        
        message = {
          "attachments": [
            {
              "contentType": "application/vnd.microsoft.card.adaptive",
              "content": 
              {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.2",
                "body": [
                  {
                      "type": "TextBlock",
                      "text": title,
                      "id": "Title",
                      "spacing": "Medium",
                      "horizontalAlignment": "Center",
                      "size": "ExtraLarge",
                      "weight": "Bolder",
                      "color": "Accent"
                  },
                  {
                    "type": "TextBlock",
                    "text": text,
                    "wrap": True,
                    "markdown": True
                  }
                ]
              }
            }
          ]
        }
        response = send_message(url, message)

        # レスポンスを確認
        if response.status_code == 200:
            print("メッセージを送信しました")
        elif response.status_code == 202:
            print("メッセージの送信を受け付けました")
        else:
            print(f"エラーが発生しました: {response.status_code}, {response.text}")

if __name__ == '__main__':
    try:
        main()
        sys.exit(0)
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        sys.exit(1)

