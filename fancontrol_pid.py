#!/usr/bin/python3

# From: https://austinsnerdythings.com/2023/07/26/controlling-asrockrack-cpu-chassis-fan-speeds-via-ipmitool-pid-loops/

import logging
import time
import PID
import datetime
import socket
import subprocess
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
# don't care about debug/info level logging from either of these packages
DESIRED_CPU_TEMP = 55.0
DESIRED_MB_TEMP = 35.0
# HDD_TEMP_THRESHOLD = 44.0 # unused
MIN_FAN_PCT = 10.0
drives_to_monitor = ['da0', 'da1', 'da2', 'da3', 'nvme0','nvme1','nvme2']
# command to set fans via ipmitool
# ipmitool raw 0x3a 0x01 0x00 0x04 0x04 0x04 0x04 0x04 0x04 0x04
                         #cpu #fan #fan #fan #fan #fan #fan ????
BASE_RAW_IPMI = 'raw 0x3a 0x01'
INITIAL_STATE = [32,32,32,32,32,32,32,32] # all 32/64 = half speed
FAN_CURRENT_STATE = INITIAL_STATE
current_sensor_readings = {}
cpu_temp_sensor = "CPU Temp"
cpu_fan_sensor = "CPU_FAN1"
case_fans = ["FRNT_FAN1","FRNT_FAN2","FRNT_FAN3"]
mb_temp_sensor = "MB Temp"
def limiter(input_value, min_value, max_value):
    if input_value < min_value:
        return min_value
    elif input_value > max_value:
        return max_value
    else:
        return input_value

def set_fans_via_ipmi():
    # raw_ipmi_cmd = construct_raw_ipmi_cmd() # not needed unless debug and remote
    # logging.info(raw_ipmi_cmd)
    result = subprocess.run(['ipmitool', 'raw', '0x3a', '0x01',
                             '0x'+FAN_CURRENT_STATE[0],
                             '0x'+FAN_CURRENT_STATE[1],
                             '0x'+FAN_CURRENT_STATE[2],
                             '0x'+FAN_CURRENT_STATE[3],
                             '0x'+FAN_CURRENT_STATE[4],
                             '0x'+FAN_CURRENT_STATE[5],
                             '0x'+FAN_CURRENT_STATE[6],
                             '0x'+FAN_CURRENT_STATE[7]], stdout=subprocess.PIPE)
    #logging.info(result.stdout)
def scale_to_64ths(input_percent):
    result = input_percent / 100.0 * 64.0
    # prepend 0 to make it a hex value
    result_int = int(result)
    result_str = str(result_int)
    if len(result_str) == 1:
        result_str = '0' + result_str # turn a 0x1 into a 0x01
    return result_str
def adjust_cpu_fan_setpoint(hex_value_64ths):
    FAN_CURRENT_STATE[0] = hex_value_64ths
def adjust_case_fan_setpoint(hex_value_64ths):
    for i in range(len(FAN_CURRENT_STATE) - 1):
        FAN_CURRENT_STATE[i + 1] = hex_value_64ths
def construct_raw_ipmi_cmd():
    new_state = BASE_RAW_IPMI
    for i in range(len(FAN_CURRENT_STATE)):
        new_state = new_state + ' 0x' + str(FAN_CURRENT_STATE[i])
    return new_state
def populate_sensor_readings(sensor, value):
    current_sensor_readings[sensor] = value
def query_ipmitool(connection):
    result = subprocess.run(['ipmitool', 'sensor'], stdout=subprocess.PIPE)
    result = result.stdout.decode('utf-8')
    for line in result.split('\n'):
        if line == '':
            break
        row_data = line.split('|')
        sensor_name = row_data[0].strip()
        sensor_value = row_data[1].strip()
        populate_sensor_readings(sensor_name, sensor_value)
        logging.debug(sensor_name + " = " + sensor_value)
def wait_until_top_of_second():
    # calculate time until next top of second
    sleep_seconds = 1 - (time.time() % 1)
    time.sleep(sleep_seconds)
def get_drive_temp(connection, drive):
    ###########################################
    # this is copilot generated, and untested #
    # not sure about row_data[0] stuff        #
    ###########################################
    result = subprocess.run(['smartctl', '-A', '/dev/' + drive], stdout=subprocess.PIPE)
    result = result.stdout.decode('utf-8')
    for line in result.split('\n'):
        if line == '':
            break
        row_data = line.split()
        if len(row_data) < 10:
            continue
        if row_data[0] == '194':
            drive_temp = row_data[9]
            logging.info(drive + " = " + drive_temp)
def query_drive_temps(connection):
    for drive in drives_to_monitor:
        get_drive_temp(connection, drive)
# tune these values. the first one is the most important and basically is the multiplier for
# how much you want the fans to run in proportion to the actual-setpoint delta.
# example: if setpoint is 55 and actual is 59, the delta is 4, which is multiplied by 4 for
# 16 output, which if converted to 64ths would be 25% fan speed.
# the 2nd parameter is the integral, which is a cumulative error counter of sorts.
# the 3rd parameter is derivative, which should probably be set to 0 (if tuned correctly, it prevents over/undershoot)
cpu_pid = PID.PID(4.0, 2.5, 0.1)
cpu_pid.SetPoint = DESIRED_CPU_TEMP
mb_pid = PID.PID(2.5, 1.5, 0.1)
mb_pid.SetPoint = DESIRED_MB_TEMP
wait_until_top_of_second()
# set last_execution to now minus one minute to force first execution
last_execution = datetime.datetime.now() - datetime.timedelta(minutes=1)
while(True):
    if datetime.datetime.now().minute != last_execution.minute:
        # TODO: get drive temps
        logging.info("getting drive temps")
    query_ipmitool(c)
    cpu_temp = float(current_sensor_readings[cpu_temp_sensor])
    mb_temp = float(current_sensor_readings[mb_temp_sensor])
    cpu_pid.update(cpu_temp)
    mb_pid.update(mb_temp)

    logging.info(f'CPU: {cpu_temp:5.2f} MB: {mb_temp:5.2f} CPU PID: {cpu_pid.output:5.2f} MB PID: {mb_pid.output:5.2f}')

    # note negative multiplier!!
    cpu_fan_setpoint = scale_to_64ths(limiter(-1*cpu_pid.output,MIN_FAN_PCT,100))
    case_fan_setpoint = scale_to_64ths(limiter(-1*mb_pid.output,MIN_FAN_PCT,100))
    adjust_cpu_fan_setpoint(cpu_fan_setpoint)
    adjust_case_fan_setpoint(case_fan_setpoint)
    set_fans_via_ipmi(c)
    last_execution = datetime.datetime.now()
    wait_until_top_of_second()
