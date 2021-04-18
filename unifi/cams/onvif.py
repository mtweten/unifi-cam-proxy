import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

import onvif

from onvif.exceptions import ONVIFError
from zeep.exceptions import Fault
from httpx import RequestError

from contextlib import suppress
from dataclasses import dataclass
from onvif import ONVIFCamera
from typing import Tuple
from requests.auth import HTTPDigestAuth 

from unifi.cams.base import UnifiCamBase

FNULL = open(os.devnull, "w")

@dataclass
class Resolution:
    """Represent video resolution."""

    width: int
    height: int

@dataclass
class Video:
    """Represent video encoding settings."""

    encoding: str
    resolution: Resolution

@dataclass
class Profile:
    """Represent a ONVIF Profile."""

    index: int
    token: str
    name: str
    video: Video

@dataclass
class Capabilities:
    """Represents Service capabilities."""

    snapshot: bool = False
    events: bool = False
    ptz: bool = False

@dataclass
class PTZ:
    """Represents PTZ configuration on a profile."""

    continuous: bool
    relative: bool
    absolute: bool
    presets: list[str] = None

class OnvifCam(UnifiCamBase):
    def __init__(self, args, logger=None):
        super(OnvifCam, self).__init__(args, logger)
        self.args = args
        #self.event_id = 0
        self.snapshot_dir = tempfile.mkdtemp()
        self.snapshot_stream = None
        #self.runner = None
        # TODO WSDL
        self.cam = ONVIFCamera(self.args.ip, 80, self.args.username, self.args.password, f"{os.path.dirname(onvif.__file__)}/wsdl/")

        #self._subscription: ONVIFService = None
    

    # async def async_pull_messages(self, _now: dt = None) -> None:
    #     pullpoint = self.device.create_pullpoint_service()
    #     response = await pullpoint.PullMessages(
    #         {"MessageLimit": 100, "Timeout": dt.timedelta(seconds=60)}
    #     )

    # def async_schedule_pull(self) -> None:
    #     """Schedule async_pull_messages to run."""
    #     self._unsub_refresh = async_call_later(self.hass, 1, self.async_pull_messages)



    @classmethod
    def add_parser(self, parser):
        super().add_parser(parser)
        parser.add_argument("--username", "-u", required=True, help="Camera username")
        parser.add_argument("--password", "-p", required=True, help="Camera password")
        # parser.add_argument("--source", "-s", required=True, help="Stream source")
        # parser.add_argument(
        #     "--http-api",
        #     default=0,
        #     type=int,
        #     help="Specify a port number to enable the HTTP API (default: disabled)",
        # )

    async def async_setup(self):
        await self.cam.update_xaddrs()

        self.capabilities = await self.async_get_capabilities()
        self.profiles = await self.async_get_profiles()
        self.logger.info(f"PROFILES: {self.profiles}")

        # No camera profiles to add
        if not self.profiles:
            # TODO need to exit
            return False

        self.stream_uris = []
        self.stream_uris.append(await self.async_get_stream_uri(self.profiles[0]))
        self.stream_uris.append(await self.async_get_stream_uri(self.profiles[1]))

    async def get_snapshot(self):
        if not self.snapshot_stream or self.snapshot_stream.poll() is not None:
            cmd = f'ffmpeg -nostdin -y -re -rtsp_transport {self.args.rtsp_transport} -i "{self.stream_uris[1]}" -vf fps=1 -update 1 {self.snapshot_dir}/screen.jpg'
            self.logger.info(f"Spawning stream for snapshots: {cmd}")
            self.snapshot_stream = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True
            )
        return "{}/screen.jpg".format(self.snapshot_dir)

        # TIMEOUTS FROM THIS, CAUSING DISCONNECTS?
        # img_file = "{}/screen.jpg".format(self.snapshot_dir)
        # snapshot_bytes = await self.cam.get_snapshot(self.profiles[0].token)
        # with open(img_file, "wb") as f:
        #     f.write(snapshot_bytes)

        # return img_file

    # async def run(self):
        

        # if self.capabilities.ptz:
        #     self.device.create_ptz_service()
        # TODO connect to motion events API somehow
    

    # async def close(self):
    #     await super().close()
    #     if self.runner:
    #         await self.runner.cleanup()

    #     if self.snapshot_stream:
    #         self.snapshot_stream.kill()

    async def continuous_move(self, payload):
        ptz_service = self.cam.create_ptz_service()
        if payload["x"] == payload["y"] == payload["z"] == 0:
            req = ptz_service.create_type("Stop")
            req.ProfileToken = self.profiles[0].token
            await ptz_service.Stop(req)
            return
            #    {"ProfileToken": req.ProfileToken, "PanTilt": True, "Zoom": False}
            #)

        req = ptz_service.create_type("ContinuousMove")
        req.ProfileToken = self.profiles[0].token
        req.Velocity = {
            "PanTilt": {"x": int(payload["x"])/1000, "y": int(payload["y"])/1000},
            "Zoom": {"x": 0},
        }

        await ptz_service.ContinuousMove(req)

    async def relative_move(self, payload):
        ptz_service = self.cam.create_ptz_service()

        req = ptz_service.create_type("RelativeMove")
        req.ProfileToken = self.profiles[0].token

        x = (float(payload["x"]) - 500.0)/1000.0
        y = -1.0 * ((float(payload["y"]) - 500.0)/1000.0)

        req.Translation = {
            "PanTilt": {"x": x, "y": y},
        }

        req.Speed = {
            "PanTilt": {"x": 1, "y": 1},
            "Zoom": {"x": 1},
        }

        await ptz_service.RelativeMove(req)
# INFO Processing [Center] message
# 2021-04-18 02:28:26 dc7fbc875b3a OnvifCam[1] DEBUG Message contents: {'from': 'UniFiVideo', 'to': 'ubnt_avclient', 'responseExpected': False, 'functionName': 'Center', 'messageId': 270583, 'inResponseTo': 0, 'payload': {'x': 155.71428571428572, 'y': 261.58730158730157}}


    # TODO
    def get_stream_source(self, stream_index: str):
        if stream_index != "video1":
            return self.stream_uris[1]

        return self.stream_uris[0]

    async def async_get_stream_uri(self, profile: Profile) -> str:
        """Get the stream URI for a specified profile."""
        media_service = self.cam.create_media_service()
        req = media_service.create_type("GetStreamUri")
        req.ProfileToken = profile.token
        req.StreamSetup = {
            "Stream": "RTP-Unicast",
            "Transport": {"Protocol": "RTSP"},
        }
        result = await media_service.GetStreamUri(req)

        return result.Uri.replace(
            "rtsp://", f"rtsp://{self.args.username}:{urllib.parse.quote(self.args.password)}@", 1
        )

    async def async_get_profiles(self) -> list[Profile]:
        """Obtain media profiles for this device."""
        media_service = self.cam.create_media_service()
        result = await media_service.GetProfiles()
        profiles = []

        if not isinstance(result, list):
            return profiles

        for key, onvif_profile in enumerate(result):
            # Only add H264 profiles
            if (
                not onvif_profile.VideoEncoderConfiguration
                or onvif_profile.VideoEncoderConfiguration.Encoding != "H264"
            ):
                continue

            profile = Profile(
                key,
                onvif_profile.token,
                onvif_profile.Name,
                Video(
                    onvif_profile.VideoEncoderConfiguration.Encoding,
                    Resolution(
                        onvif_profile.VideoEncoderConfiguration.Resolution.Width,
                        onvif_profile.VideoEncoderConfiguration.Resolution.Height,
                    ),
                ),
            )

            # Configure PTZ options
            if self.capabilities.ptz and onvif_profile.PTZConfiguration:
                profile.ptz = PTZ(
                    onvif_profile.PTZConfiguration.DefaultContinuousPanTiltVelocitySpace
                    is not None,
                    onvif_profile.PTZConfiguration.DefaultRelativePanTiltTranslationSpace
                    is not None,
                    onvif_profile.PTZConfiguration.DefaultAbsolutePantTiltPositionSpace
                    is not None,
                )

                try:
                    ptz_service = self.cam.create_ptz_service()
                    presets = await ptz_service.GetPresets(profile.token)
                    profile.ptz.presets = [preset.token for preset in presets if preset]
                except (Fault, RequestError):
                    # It's OK if Presets aren't supported
                    profile.ptz.presets = []

            profiles.append(profile)

        return profiles

    async def async_get_capabilities(self):
        """Obtain information about the available services on the device."""
        snapshot = False
        with suppress(ONVIFError, Fault, RequestError):
            media_service = self.cam.create_media_service()
            media_capabilities = await media_service.GetServiceCapabilities()
            snapshot = media_capabilities and media_capabilities.SnapshotUri

        pullpoint = False
        # with suppress(ONVIFError, Fault, RequestError):
        #     pullpoint = await self.events.async_start()

        ptz = False
        with suppress(ONVIFError, Fault, RequestError):
            self.cam.get_definition("ptz")
            ptz = True

        return Capabilities(snapshot, pullpoint, ptz)