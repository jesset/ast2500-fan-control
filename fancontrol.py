#!/root/venv/fan_control/bin/python3

import subprocess
import re
import time
import datetime

import numpy as np

ipmitool = "/usr/bin/ipmitool"  # path to ipmitool (Fan speed monitoring/control)
smartctl = "/usr/sbin/smartctl" # path to smartctl (HDD temperature)
smi = "/usr/bin/nvidia-smi"     # path to nvidia-smi (GPU temperature/activity)
lmSensors = "/usr/bin/sensors"  # path to sensors (CPU temperature)

# list of disks to poll for temperature
hdds = ['/dev/sda','/dev/sdb','/dev/sdc','/dev/sdd']

# path to log file
logfile = '/root/venv/fan_control/logs'

# Object contains the temperature settings for each fan speed
tempPoints = {
    "cpu": [40, 60, 80],
    "hdds": [20, 37, 45, 50],
    "gpu": [50, 60, 70]
}

# Object contains the fan speed settings for each component
fanSpeedPoints = {
    "cpu": [25, 50, 100],
    "hdds": [15, 35, 50, 100],
    "gpu": [25, 50, 100]
}

# Current fan speed (in RPM)

# The current, minimum, and maximum fan speeds
# cpu, rear, front1, front2, front3, front4
# cpu, rear, gpu,    top,    bottom, chipset
fanSpeeds = {
    "current" : [0,0,0,0,0,0],
    "min" : [1,1,1,1,1,1],
    "max" : [2,2,2,2,2,2]
}
fanSpeedRe = [
    r"^CPU_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^REAR_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^FRONT_FAN1.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^FRONT_FAN2.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^FRONT_FAN3.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$",
    r"^FRONT_FAN4.*\|\s([0-9][0-9][0-9]|[0-9][0-9][0-9][0-9])\sRPM$"
]

# get each hdd temperature
# #!/bin/bash
# DRIVEPATH="$1"
# INFO="$(sudo smartctl -a $DRIVEPATH)"
# TEMP=$(echo "$INFO" | grep '194 Temp' | awk '{print $10}')
# if [[ $TEMP == '' ]]; then
#   TEMP=$(echo "$INFO" | grep '190 Airflow' | awk '{print $10}')
# fi
# if [[ $TEMP == '' ]]; then
#   TEMP=$(echo "$INFO" | grep 'Temperature Sensor 1:' | awk '{print $4}')
# fi
# if [[ $TEMP == '' ]]; then
#   TEMP=$(echo "$INFO" | grep 'Current Drive Temperature:' | awk '{print $4}')
# fi
# if [[ $TEMP == '' ]]; then
#   TEMP=$(echo "$INFO" | grep 'Temperature:' | awk '{print $2}')
# fi
# echo $TEMP

# def get_fan_speed(temperature):
#     if temperature < temp_points.min():
#         return 0
#     elif temperature > temp_points.max():
#         return 100
#     else:
#         return np.interp(temperature, temp_points, fan_speed_points)

# Current fan speed: ipmitool raw 0x3a 0x02

# fan map : cpu, nc, rear_fan1(exhaust), nc, front_fan1(gpu), front_fan2(top hd), front_fan3(bottom hd), front_fan4 (uncontrolled, chipset)


# various globals
hdchecktime = time.time()
# hdFanSpeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]

# def log(message):
#     with open(logfile,'a') as log:
#         log.write(str(datetime.datetime.now()))
#         log.write(' ')
#         log.write(str(message))
#         log.write('\n')

def getFanSpeeds():
    try:
        # Checks each fan speed and puts it into the current fan speed array
        for i in range(len(fanSpeeds["current"])):
            fanSpeeds["current"][i] = re.search(re.compile(fanSpeedRe[i], re.MULTILINE),).group(1)
        return None
    except Exception as e:
        print(f"exception in get_cpu_fan_speed: {e}")

def getCpuTemp():
    try:
        return int(
            re.search(
                re.compile(r'^CPU\sTemp.*\|\s([0-9][0-9])\sdegrees\sC$', re.MULTILINE), 
                subprocess.check_output(
                    [ipmitool,'sdr','type','Temperature']
                ).decode('utf-8')
            ).group(1)
        )
    except Exception as e:
        print(f"exception in get_cpu_temp: {e}")
        # TODO set all fans to full
        print(f"cpu temp detection failure, all fans set to 100%")

def checkcputemp():
    global currentcpufanspeed
    global cpuoverride
    try:
        currentcputemp = getcputemp()
        if currentcputemp > cpu_override_temp and cpuoverride == False:
            subprocess.run(allfanshigh)
            cpuoverride = True
            log('cpu temp > '+str(cpu_override_temp)+'C, all fans set to 100%')
        elif currentcputemp < cpu_normal_temp and cpuoverride == True:
            subprocess.run(hdfanspeed)
            cpuoverride = False
            log('cpu temp < '+str(cpu_normal_temp)+'C, cpu fan set to '+str(cpu_fan_default)+'%')
    except Exception as e:
        log(e)

def hdtemp(dev):
    try:
        temp = subprocess.check_output([hddtemp,dev])
        temp = re.match('^.*([0-9][0-9])°C$', temp.decode('utf-8'))
        temp = temp.group(1)
        return temp
    except Exception as e:
        log(e)
        subprocess.run(allfanshigh)
        log('hd temp detection failure, all fans set to 100%')

def checkhdtemps():
    hdtemps = []
    global hdchecktime
    global currenthdfanspeed
    global hdfanspeed
    if cpuoverride == False:
        try:
            for hdd in hdds:
                hdtemps.append(int(hdtemp(hdd)))
            if any(x >= hd_hi for x in hdtemps):
                currenthdfanspeed = hex(hd_fans_hi)
                hdfanspeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]
                subprocess.run(hdfanspeed)
                log('hd temp >= '+str(hd_hi)+',C fans set to '+str(hd_fans_hi)+'%')
            elif any(x == hd_medhi for x in hdtemps):
                currenthdfanspeed = hex(hd_fans_medhi)
                hdfanspeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]
                subprocess.run(hdfanspeed)
                log('hd temp '+str(hd_medhi)+',C fans set to '+str(hd_fans_medhi)+'%')
            elif any(x == hd_medlo for x in hdtemps):
                currenthdfanspeed = hex(hd_fans_medlo)
                hdfanspeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]
                subprocess.run(hdfanspeed)
                log('hd temp '+str(hd_medlo)+'C, fans set to '+str(hd_fans_medlo)+'%')
            elif all(x <= hd_lo for x in hdtemps):
                currenthdfanspeed = hex(hd_fans_lo)
                hdfanspeed = [ipmitool,'raw','0x3a','0x01',currentcpufanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed,currenthdfanspeed]
                subprocess.run(hdfanspeed)
                log('hd temp <= '+str(hd_lo)+'C, fans set to '+str(hd_fans_lo)+'%')
        except Exception as e:
            log(e)
    else:
        log('cpu temp override active, no action taken on hd fans')
    hdchecktime = time.time()

checkhdtemps()

while True:
    checkcputemp()
    currenttime = time.time()
    if currenttime - hdchecktime >= hd_poll:
        checkhdtemps()
    time.sleep(1)
