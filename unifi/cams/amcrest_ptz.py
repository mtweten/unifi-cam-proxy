import logging
import os
import shutil
import subprocess
import sys
import tempfile
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

    def __init__(self, args, logger=None):
        self.logger = logger
        self.args = args
        self.dir = tempfile.mkdtemp()
        self.streams = {}

        self.logger.info("Username: %s, Password: %s", self.args.username, self.args.password)
        self.cam = AmcrestCamera(self.args.ip, 80, self.args.username, self.args.password).camera

    def get_snapshot(self):
        img_file = "{}/screen.jpg".format(self.dir)
        self.cam.snapshot(1, img_file)
        return img_file

    def continuous_move(self, options):
        action = "stop"
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
        
        self.cam.ptz_control_command(action=action, code=code, arg1=arg1, arg2=arg2, arg3=arg3)

    def start_video_stream(
        self, stream_index: str, stream_name: str, destination: Tuple[str, int]
    ):
        # todo CHANNELS
        vid_src = self.cam.rtsp_url()

        cmd = 'ffmpeg -y -f lavfi -i aevalsrc=0 -i "{}" -vcodec copy -use_wallclock_as_timestamps 1 -strict -2 -c:a aac -metadata streamname={} -f flv - | {} -m unifi.clock_sync | nc {} {}'.format(
            vid_src,
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
