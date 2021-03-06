from picamera import PiCamera
from gps import *
import datetime, time, board, os, signal, subprocess, threading, concurrent.futures, busio
import adafruit_adxl34x
import RPi.GPIO as GPIO
from goprocam import GoProCamera, constants

"""
Initialize/setup all our important items
Camera, GPIO mode, accelorometer, mic
"""
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

"""
Global definition for time window of recording/reading information and other info
"""
echo = 5
trig = 6
stale_limit=5 #in seconds
stale_reset_distance=0.00001

running = True
time_sync = False #used for determining whether to use perfs or time


"""
Set up of GPIO pins
"""
GPIO.setup(echo, GPIO.IN) #pin that reads the proximity
GPIO.setup(trig, GPIO.OUT) #pin that triggers the proximity sensor

"""
Class GPSpoller
Will continuously be pulling/reading in the GPS coordinates
Separate class since this will always be running due to extended boot time if turned on/off
"""
class GPSpoller(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.session = gps(mode=WATCH_ENABLE)
        self.current_value = None
        self.set_of_values = [None, None] #current_value, perf_counter

    def get_current_value(self):
        return self.current_value

    def get_set_of_values(self):
        return self.set_of_values

    """
    function that sends that records the current gps data and determines if its stale
    """
    def upload_data(self, glob_time):
        print('Trying to upload')
        global stale_limit

        new_perf = time.perf_counter()

        #makes sure the gps has at least gotten one reading
        if self.set_of_values[0] == None:
            print('new')
            file_text = "Current perf: " + str(new_perf)
            print(file_text, file = open('/home/pi/Recycling-ML-Project-johns_testing/stop_locations/' + str(glob_time) + '.txt', 'a'))
            return

        #gets values necessary for the print statement
        perf_recorded = self.set_of_values[1]
        latitude = getattr(self.set_of_values[0], 'lat', 0.0)
        longitude = getattr(self.set_of_values[0], 'lon', 0.0)
        time_recorded = getattr(self.set_of_values[0], 'time', '')

        #prints data to file while determining if it is stale
        if time.perf_counter() - perf_recorded < stale_limit:
            print('not stale')
            file_text = "First Perf: " + str(perf_recorded) + "\nLatitude: " + str(latitude) + "\nLongitude: " + str(longitude) + "\nFirst Time: " +  time_recorded + "\nCurrent perf: " + str(new_perf)
            print(file_text, file = open('/home/pi/Recycling-ML-Project-johns_testing/stop_locations/' + str(glob_time) + '.txt', 'a'))
        else:
            print('stale')
            file_text = "First Perf: " + str(perf_recorded) + "\nLatitude: " + str(latitude) + "\nLongitude: " + str(longitude) + "\nFirst Time: " +  time_recorded + "\nCurrent perf: " + str(new_perf) + "\nData is stale"
            print(file_text, file = open('/home/pi/Recycling-ML-Project-johns_testing/stop_locations/' + str(glob_time) + '.txt', 'a'))

    """
    what will constantly happen as the program runs
    """
    def run(self):
        #default values
        global time_sync
        global stale_reset_distance
        old_lat=-1000
        old_lon=-1000

        try:
            while running:
                self.current_value = self.session.next()
                #only happens if the gps gets a reading
                if (self.current_value != None):
                    if getattr(self.current_value, 'lat', 0.0) != 0.0:
                        latitude = getattr(self.current_value, 'lat', 0.0)
                        longitude = getattr(self.current_value, 'lon',0.0)
                        #only happens if this is not the first reading
                        if(self.set_of_values[0] != None):
                            old_lat = getattr(self.set_of_values[0], 'lat', 0.0)
                            old_lon = getattr(self.set_of_values[0], 'lon', 0.0)
                        #only happens if this is first reading
                        if(self.current_value['class'] == 'TPV' and time_sync == False):
                            strt_time = "Perf Counter:" + str(time.perf_counter()) +'\nStartup Time:' + getattr(self.current_value, 'time', '')
                            print(strt_time + "\nLatitude: " + str(latitude) + "\nLongitude: " + str(longitude), file = open('/home/pi/Recycling-ML-Project-johns_testing/gps_startup_times/' + str(time.time()) + '.txt', 'a'))
                            self.set_of_values = [self.current_value, time.perf_counter()]
                            time_sync = True
                        #only updates set_of_values if gps has been moving
                        elif(self.current_value['class'] == 'TPV' and (abs(float(latitude) - float(old_lat)) >= stale_reset_distance or abs(float(longitude) - float(old_lon)) >= stale_reset_distance)):
                            self.set_of_values[0]=self.current_value
                            self.set_of_values[1]=time.perf_counter()
                            old_lat = getattr(self.current_value, 'lat', 0.0)
                            old_lon = getattr(self.current_value, 'lon', 0.0)
                        else:
                            pass
                    time.sleep(0.2)

        except StopIteration:
            pass

"""
function that records video with the gopro camera
will have to get time/gps information form the meta data

"""
def run_gopro():
    print('entering gopro method')
    goproCamera = GoProCamera.GoPro()
    my_mac_address="d6:32:60:1d:b6:6e"
    goproCamera.power_on(my_mac_address)
    #goproCamera.video_settings('480p', fps='30')
    goproCamera.shoot_video(10)

#Just to get the official start time that will be fed into all the threads
def globalTimer():
    global gpsp
    global time_sync
    report=gpsp.get_current_value()
    if report['class'] == 'TPV':
        return getattr(report, 'time', '')
    elif time_sync:
        return str(datetime.datetime.now())
    else:
        return time.perf_counter()

"""
Main method
While loop that will continuously run, waiting for motion sensor to trigger collection
of the data.
"""
def main():
    global running
    global gpsp

    previousCoordinates = "File_name_n_a"

    #keeps us from getting wierd errors
    report=None
    while(report == None):
        report=gpsp.get_current_value()

    first_perf= time.perf_counter()
    if report['class'] == 'TPV':
        start= getattr(report, 'time', '')
        latitude = report.lat
        longitude = report.lon
        file_text = 'Time: '+ start + '\nPerf: ' + first_perf + '\nLatitude: ' + latitude + '\nLongitude: ' + longitude
        print(file_text, file = open("/home/pi/Recycling-ML-Project-johns_testing/starting_states/" + str(start) + " " + str(first_perf) + ".txt", "a"))
    else:
        print('Perf: ' + str(first_perf), file = open("/home/pi/Recycling-ML-Project-johns_testing/starting_states/" + str(first_perf) + ".txt", "a"))

    while running:
        try:
            GPIO.output(trig, GPIO.HIGH)
            time.sleep(0.001)
            GPIO.output(trig, GPIO.LOW)

            count = time.perf_counter()
            pulse = time.perf_counter()
            while GPIO.input(echo) == 0 and pulse - count < 0.1:
                pulse = time.perf_counter()

            count = time.perf_counter()
            pulse_end = time.perf_counter()
            while GPIO.input(echo) == 1 and pulse_end - count < 0.1:
                pulse_end = time.perf_counter()

            distance = round((pulse_end - pulse) * 17150, 2) #converts to cm

            globalTime = globalTimer()

            if distance < 15:

                gpsp.upload_data(globalTime)
                #GPIO.output(Relay_Ch1, GPIO.HIGH)
                print("distance less than 15, processing camera\n")
                thread1 = threading.Thread(name='cam_thread', target=run_gopro)
                thread1.start()

                thread1.join()
                #GPIO.output(Relay_Ch1, GPIO.LOW)
                print("Video successfully captured")

        except KeyboardInterrupt:
            running=False

            print("keyboard interrupt, program terminating")
            activeThreads = threading.enumerate()
            print(activeThreads)
            #GPIO.output(Relay_Ch1, GPIO.LOW) #Turn off Relay Board
            GPIO.cleanup()
            sys.exit()

if __name__ == "__main__":
    gpsp = GPSpoller()
    gpsp.start()
    main()