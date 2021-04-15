import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

from typing import Tuple

from amcrest import AmcrestCamera
from requests.auth import HTTPDigestAuth 

from unifi.cams.base import UnifiCamBase

FNULL = open(os.devnull, "w")

class AmcrestPTZCam(UnifiCamBase):
    @classmethod
    def add_parser(self, parser):
        parser.add_argument("--username", "-u", required=True, help="Camera username")
        parser.add_argument("--password", "-p", required=True, help="Camera password")
        parser.add_argument("--rtsp-url", "-r", required=False, help="Alternative RTSP url")

    def __init__(self, args, logger=None):
        self.logger = logger
        self.args = args
        self.dir = tempfile.mkdtemp()
        self.cam = AmcrestCamera(self.args.ip, 80, self.args.username, self.args.password).camera

        self.rtsp_url = self.args.rtsp_url if self.args.rtsp_url else self.cam.rtsp_url()
        #hack
        self.rtsp_url = self.rtsp_url.replace(self.args.password, urllib.parse.quote(self.args.password))
        
        self.logger.info(self.dir)
        cmd = f'ffmpeg -y -re -rtsp_transport tcp -i "{self.rtsp_url}" -vf fps=1 -update 1 {self.dir}/screen.jpg'
        self.logger.info(cmd)
        self.streams = {
            "mjpg": subprocess.Popen(
                cmd, stdout=FNULL, stderr=subprocess.STDOUT, shell=True
            )
        }

    def get_snapshot(self):
        return "{}/screen.jpg".format(self.dir)
        # img_file = "{}/screen.jpg".format(self.dir)
        # self.cam.snapshot(1, img_file)
        # return img_file

    def continuous_move(self, options):
        action = "stop"
        # Doesn't seem to matter if we're stopping
        code = "None"

        arg1 = arg2 = arg3 = 0

        if options["x"] < 0:
            action = "start"
            arg2 = 1
            code = "Left"
        elif options["x"] > 0:
            action = "start"
            arg2 = 1
            code = "Right"

        if options["y"] > 0:
            arg2 = 1
            if action == "start":
                arg1 = 1
                code = code + "Up"
            else:
                code = "Up"
            action = "start"
        elif options["y"] < 0:
            arg2 = 1
            if action == "start":
                arg1 = 1
                code = code + "Down"
            else:
                code = "Down"
            action = "start"
            
        # Seems like it has to be a valid code
        if code == "None":
            code = "Down"
        
        # TODO don't block? set and forget
        self.cam.ptz_control_command(action=action, code=code, arg1=arg1, arg2=arg2, arg3=arg3)

    def start_video_stream(
        self, stream_index: str, stream_name: str, destination: Tuple[str, int]
    ):
        # todo CHANNELS
        # TODO use alternative rtsp to use the rtsp-simple-server to reduce load. Or try and use the actual amcrest api instead

        cmd = 'ffmpeg -y -f lavfi -i aevalsrc=0 -rtsp_transport tcp -i "{}" -vcodec copy -strict -2 -c:a aac -metadata streamname={} -f flv - | {} -m unifi.clock_sync | nc {} {}'.format(
            self.rtsp_url,
            stream_name,
            sys.executable,
            destination[0],
            destination[1],
        )
        self.logger.info("Spawning ffmpeg: %s", cmd)
        if (
            stream_name not in self.streams
            or self.streams[stream_name].poll() is not None
        ):
            self.streams[stream_name] = subprocess.Popen(
                cmd, stdout=FNULL, stderr=subprocess.STDOUT, shell=True
            )

    # def get_video_settings(self):
    #     r = self.cam.PTZCtrl.channels[1].status(method="get")["PTZStatus"][
    #         "AbsoluteHigh"
    #     ]
    #     return {
    #         # Tilt/elevation
    #         "brightness": int(100 * int(r["azimuth"]) / 3600),
    #         # Pan/azimuth
    #         "contrast": int(100 * int(r["azimuth"]) / 3600),
    #         # Zoom
    #         "hue": int(100 * int(r["absoluteZoom"]) / 40),
    #     }

    def change_video_settings(self, options):
        #percentage?
        # scale of amcrest is 0-128
        zoom_pos_percent = options["zoomPosition"]
        self.logger.info("UNIFI PROTECT SETTING ZOOM POSITION TO: %s", zoom_pos_percent)
        
        status = self.cam.ptz_status
        self.logger.info("CURRENT PTZ STATUS IS: %s", status)
        