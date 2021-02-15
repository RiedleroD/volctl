"""
PulseAudio manager.

Interacts with auto-generated lib_pulseaudio ctypes bindings.
"""

import sys
from ctypes import cast, c_void_p, c_ubyte, c_ulong, POINTER
from gi.repository import GObject

from volctl.lib.pulseaudio import (
    # types
    pa_cvolume,
    pa_volume_t,
    pa_subscription_mask_t,
    pa_sink_info_cb_t,
    pa_context_notify_cb_t,
    pa_context_subscribe_cb_t,
    pa_client_info_cb_t,
    pa_server_info_cb_t,
    pa_sink_input_info_cb_t,
    pa_context_success_cb_t,
    pa_stream_request_cb_t,
    pa_sample_spec,
    # mainloop
    pa_threaded_mainloop_new,
    pa_threaded_mainloop_get_api,
    pa_threaded_mainloop_start,
    pa_threaded_mainloop_signal,
    # context
    pa_context_new,
    pa_context_connect,
    pa_context_disconnect,
    pa_context_set_state_callback,
    pa_context_subscribe,
    pa_context_set_subscribe_callback,
    pa_context_get_state,
    pa_context_get_client_info_list,
    pa_context_get_sink_info_list,
    pa_context_get_sink_input_info_list,
    pa_context_get_client_info,
    pa_context_get_server_info,
    pa_context_get_sink_info_by_index,
    pa_context_get_sink_input_info,
    pa_context_set_sink_volume_by_index,
    pa_context_set_sink_mute_by_index,
    pa_context_set_sink_input_volume,
    pa_context_set_sink_input_mute,
    # misc
    pa_operation_unref,
    pa_proplist_to_string,
    # stream monitoring
    pa_stream_connect_record,
    pa_stream_new,
    pa_stream_set_monitor_stream,
    pa_stream_set_read_callback,
    pa_stream_peek,
    pa_stream_drop,
    pa_stream_disconnect,
    # constants
    PA_CONTEXT_READY,
    PA_SUBSCRIPTION_MASK_SINK,
    PA_SUBSCRIPTION_MASK_SINK_INPUT,
    PA_SUBSCRIPTION_MASK_CLIENT,
    PA_CONTEXT_FAILED,
    PA_CONTEXT_TERMINATED,
    PA_SUBSCRIPTION_EVENT_FACILITY_MASK,
    PA_SUBSCRIPTION_EVENT_CLIENT,
    PA_SUBSCRIPTION_EVENT_REMOVE,
    PA_SUBSCRIPTION_EVENT_SINK,
    PA_SUBSCRIPTION_EVENT_TYPE_MASK,
    PA_SUBSCRIPTION_EVENT_SINK_INPUT,
    PA_SAMPLE_U8,
    PA_STREAM_ADJUST_LATENCY,
    PA_STREAM_DONT_MOVE,
    PA_STREAM_PEAK_DETECT,
)

METER_RATE = 25  # in Hz


def cvolume_from_volume(volume, channels):
    """Convert single-value volume to PA cvolume."""
    cvolume = pa_cvolume()
    cvolume.channels = channels
    vol = pa_volume_t * 32
    cvolume.values = vol()
    for i in range(0, channels):
        cvolume.values[i] = volume
    return cvolume


class PulseAudio:
    """Handles connection to PA. Sets up callbacks."""

    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        new_client_cb,
        remove_client_cb,
        new_sink_cb,
        remove_sink_cb,
        new_sink_input_cb,
        remove_sink_input_cb,
        default_sink_cb,
    ):
        # pylint: disable=too-many-arguments

        self.new_client_cb = new_client_cb
        self.new_sink_input_cb = new_sink_input_cb
        self.remove_sink_input_cb = remove_sink_input_cb
        self.remove_client_cb = remove_client_cb
        self.new_sink_cb = new_sink_cb
        self.remove_sink_cb = remove_sink_cb
        self.default_sink_cb = default_sink_cb

        self.pa_mainloop = pa_threaded_mainloop_new()
        self.pa_mainloop_api = pa_threaded_mainloop_get_api(self.pa_mainloop)

        self.context = pa_context_new(self.pa_mainloop_api, "volctl".encode("utf-8"))
        self.__context_notify_cb = pa_context_notify_cb_t(self._context_notify_cb)
        pa_context_set_state_callback(self.context, self.__context_notify_cb, None)
        pa_context_connect(self.context, None, 0, None)

        # create callbacks
        self.__null_cb = pa_context_success_cb_t(self._null_cb)
        self.__pa_sink_info_cb = pa_sink_info_cb_t(self._pa_sink_info_cb)
        self.__pa_context_subscribe_cb = pa_context_subscribe_cb_t(
            self._pa_context_subscribe_cb
        )
        self.__pa_sink_input_info_list_cb = pa_sink_input_info_cb_t(
            self._pa_sink_input_info_cb
        )
        self.__pa_client_info_list_cb = pa_client_info_cb_t(self._pa_client_info_cb)
        self.__pa_server_info_cb = pa_server_info_cb_t(self._pa_server_info_cb)

        pa_threaded_mainloop_start(self.pa_mainloop)

    def set_sink_volume(self, index, cvolume):
        """Set volume for a sink by index."""
        operation = pa_context_set_sink_volume_by_index(
            self.context, index, cvolume, self.__null_cb, None
        )
        pa_operation_unref(operation)

    def set_sink_mute(self, index, mute):
        """Set mute for a sink by index."""
        operation = pa_context_set_sink_mute_by_index(
            self.context, index, mute, self.__null_cb, None
        )
        pa_operation_unref(operation)

    def set_sink_input_volume(self, index, cvolume):
        """Set mute for a sink input by index."""
        operation = pa_context_set_sink_input_volume(
            self.context, index, cvolume, self.__null_cb, None
        )
        pa_operation_unref(operation)

    def set_sink_input_mute(self, index, mute):
        """Set mute for a sink input by index."""
        operation = pa_context_set_sink_input_mute(
            self.context, index, mute, self.__null_cb, None
        )
        pa_operation_unref(operation)

    def disconnect(self):
        """Terminate connection to PA."""
        pa_context_disconnect(self.context)

    def _context_notify_cb(self, context, userdata):
        state = pa_context_get_state(context)

        if state == PA_CONTEXT_READY:
            self._request_update()

            pa_context_set_subscribe_callback(
                self.context, self.__pa_context_subscribe_cb, None
            )
            submask = (pa_subscription_mask_t)(
                PA_SUBSCRIPTION_MASK_SINK
                | PA_SUBSCRIPTION_MASK_SINK_INPUT
                | PA_SUBSCRIPTION_MASK_CLIENT
            )
            operation = pa_context_subscribe(
                self.context, submask, self.__null_cb, None
            )
            pa_operation_unref(operation)
            print("PulseAudio: Connection ready", file=sys.stderr)

        elif state == PA_CONTEXT_FAILED:
            print("PulseAudio: Connection failed", file=sys.stderr)
            pa_threaded_mainloop_signal(self.pa_mainloop, 0)
            sys.exit(1)

        elif state == PA_CONTEXT_TERMINATED:
            print("PulseAudio: Connection terminated", file=sys.stderr)
            pa_threaded_mainloop_signal(self.pa_mainloop, 0)

    def _request_update(self):
        operation = pa_context_get_server_info(
            self.context, self.__pa_server_info_cb, None
        )
        pa_operation_unref(operation)

        operation = pa_context_get_client_info_list(
            self.context, self.__pa_client_info_list_cb, None
        )
        pa_operation_unref(operation)

        operation = pa_context_get_sink_info_list(
            self.context, self.__pa_sink_info_cb, None
        )
        pa_operation_unref(operation)

        operation = pa_context_get_sink_input_info_list(
            self.context, self.__pa_sink_input_info_list_cb, True
        )
        pa_operation_unref(operation)

    def _pa_context_subscribe_cb(self, context, event_type, index, user_data):
        efac = event_type & PA_SUBSCRIPTION_EVENT_FACILITY_MASK
        etype = event_type & PA_SUBSCRIPTION_EVENT_TYPE_MASK
        if efac == PA_SUBSCRIPTION_EVENT_CLIENT:
            if etype == PA_SUBSCRIPTION_EVENT_REMOVE:
                self.remove_client_cb(int(index))
            else:
                operation = pa_context_get_client_info(
                    self.context, index, self.__pa_client_info_list_cb, None
                )
                pa_operation_unref(operation)

        elif efac == PA_SUBSCRIPTION_EVENT_SINK:
            if etype == PA_SUBSCRIPTION_EVENT_REMOVE:
                self.remove_sink_cb(int(index))
            else:
                operation = pa_context_get_sink_info_by_index(
                    self.context, int(index), self.__pa_sink_info_cb, True
                )
                pa_operation_unref(operation)

        elif efac == PA_SUBSCRIPTION_EVENT_SINK_INPUT:
            if etype == PA_SUBSCRIPTION_EVENT_REMOVE:
                self.remove_sink_input_cb(int(index))
            else:
                operation = pa_context_get_sink_input_info(
                    self.context, int(index), self.__pa_sink_input_info_list_cb, True,
                )
                pa_operation_unref(operation)

    def _pa_client_info_cb(self, context, struct, c_int, user_data):
        if struct:
            self.new_client_cb(
                struct.contents.index,
                struct.contents,
                self._dict_from_proplist(struct.contents.proplist),
            )

    def _pa_sink_input_info_cb(self, context, struct, index, user_data):
        if struct and user_data:
            self.new_sink_input_cb(
                int(struct.contents.index),
                struct.contents,
                self._dict_from_proplist(struct.contents.proplist),
            )

    def _pa_sink_info_cb(self, context, struct, index, data):
        if struct:
            self.new_sink_cb(
                int(struct.contents.index),
                struct.contents,
                self._dict_from_proplist(struct.contents.proplist),
            )

    def _pa_server_info_cb(self, context, struct, data):
        if struct:
            self.default_sink_cb(struct.contents.default_sink_name)

    @staticmethod
    def _null_cb(param_a=None, param_b=None, param_c=None, param_d=None):
        return

    @staticmethod
    def _dict_from_proplist(proplist):
        props = {}
        proplist = pa_proplist_to_string(proplist).split("\n".encode("utf-8"))
        for prop in proplist:
            left, _, right = prop.partition("=".encode("utf-8"))
            props[left.strip()] = right.strip()[1:-1]
        return props


class PulseAudioManager:
    """
    Main PulseAudio interface.

    Provides methods to UI. Internally uses PulseAudio object. Keeps track of
    connected clients, sinks, sink inputs.
    """

    def __init__(self, volctl):
        self.volctl = volctl
        self._pa_clients = {}
        self._pa_sinks = {}
        self._pa_sinks_by_name = {}
        self._default_sink = None
        self._pa_sink_inputs = {}
        self._pulseaudio = PulseAudio(
            self._on_new_pa_client,
            self._on_remove_pa_client,
            self._on_new_pa_sink,
            self._on_remove_pa_sink,
            self._on_new_pa_sink_input,
            self._on_remove_pa_sink_input,
            self._on_default_sink,
        )
        self.context = self._pulseaudio.context
        self.samplespec = pa_sample_spec()
        self.samplespec.channels = 1
        self.samplespec.format = PA_SAMPLE_U8
        self.samplespec.rate = METER_RATE

    @property
    def mainloop(self):
        """Get PulseAudio mainloop."""
        return self._pulseaudio.pa_mainloop

    @property
    def pa_sinks(self):
        """Get PulseAudio sinks."""
        return self._pa_sinks

    @property
    def pa_sink_inputs(self):
        """Get PulseAudio sink inputs."""
        return self._pa_sink_inputs

    def get_pa_client(self, client):
        """Return PulseAudio client."""
        return self._pa_clients[client]

    def close(self):
        """Close PA manager."""
        self._pulseaudio.disconnect()

    # called by Sink, SinkInput objects

    def get_first_sink(self):
        """Returns first sink (master volume)"""
        try:
            first_key = list(self._pa_sinks.keys())[0]
            return self._pa_sinks[first_key]
        except IndexError:
            return None

    def get_main_sink(self):
        """Returns sink for master volume"""
        if self._default_sink is None:
            return self.get_first_sink()

        return self._pa_sinks_by_name[self._default_sink]

    def is_main_sink(self, sink_name):
        """Checks, whether the sink with the passed name is the default (main) sink."""
        return sink_name == self._default_sink

    def set_sink_volume(self, index, cvolume):
        """Set sink volume by index."""
        self._pulseaudio.set_sink_volume(index, cvolume)

    def set_sink_mute(self, index, mute):
        """Set sink mute by index."""
        self._pulseaudio.set_sink_mute(index, mute)

    def set_sink_input_volume(self, index, cvolume):
        """Set sink input volume by index."""
        self._pulseaudio.set_sink_input_volume(index, cvolume)

    def set_sink_input_mute(self, index, mute):
        """Set sink input mute by index."""
        self._pulseaudio.set_sink_input_mute(index, mute)

    # called by gui thread -> lock pa thread

    def set_main_volume(self, volume):
        """Set main volume"""
        self.get_main_sink().set_volume(volume)

    def toggle_main_mute(self):
        """Toggle main mute"""
        sink = self.get_main_sink()
        sink.set_mute(not sink.mute)

    # callbacks called by pulseaudio

    def _on_new_pa_client(self, index, struct, props):
        if index not in self._pa_clients:
            self._pa_clients[index] = Client(self, index)
        self._pa_clients[index].update(struct, props)

    def _on_remove_pa_client(self, index):
        if index in self._pa_clients:
            del self._pa_clients[index]

    def _on_new_pa_sink(self, index, struct, props):
        if index not in self._pa_sinks:
            sink = Sink(self, index, struct, props)
            self._pa_sinks[index] = sink
            self._pa_sinks_by_name[sink.sink_name] = sink
            GObject.idle_add(self.volctl.slider_count_changed)
        else:
            sink = self._pa_sinks[index]
            old_name = sink.sink_name

            sink.update(struct, props)

            del self._pa_sinks_by_name[old_name]
            self._pa_sinks_by_name[sink.sink_name] = sink

    def _on_remove_pa_sink(self, index):
        sink = self._pa_sinks.pop(index)
        del self._pa_sink_index_by_name[sink.sink_name]
        GObject.idle_add(self.volctl.slider_count_changed)

    def _on_new_pa_sink_input(self, index, struct, props):
        # filter out strange events
        if struct.name == "audio-volume-change":
            return
        # unknown if this is the right way to filter for applications
        # but seems to keep away things like loopback module etc.
        if struct.driver.decode("utf-8") not in ("protocol-native.c", "PipeWire"):
            return

        if index not in self._pa_sink_inputs:
            self._pa_sink_inputs[index] = SinkInput(self, index, struct, props)
            GObject.idle_add(self.volctl.slider_count_changed)
        else:
            self._pa_sink_inputs[index].update(struct, props)

    def _on_remove_pa_sink_input(self, index):
        if index in self._pa_sink_inputs:
            del self._pa_sink_inputs[index]
            GObject.idle_add(self.volctl.slider_count_changed)

    def _on_default_sink(self, name):
        self._default_sink = name

class AbstractMonitorableSink:
    """Base class for Sinks."""

    def __init__(self, pa_mgr, idx):
        self.pa_mgr = pa_mgr
        self.idx = idx
        self.volume = 0
        self.channels = 0
        self.mute = False
        self._icon_name = None
        self._name = ""
        self._stream = None
        self._on_stream_read_ctypes = pa_stream_request_cb_t(self._on_stream_read)
        self._is_sink_input = isinstance(self, SinkInput)

    def update(self, struct, _):
        """Update sink properties."""
        self.volume = struct.volume.values[0]
        self.channels = struct.volume.channels
        self.mute = bool(struct.mute)

    @property
    def name(self):
        """Sink name"""
        return self._name

    @property
    def icon_name(self):
        """Sink input icon name"""
        return self._icon_name

    @property
    def sink_idx(self):
        """Sink index"""
        return self.idx

    def monitor_stream(self):
        if self._stream is not None:
            pa_stream_disconnect(self._stream)

        self._stream = pa_stream_new(
            self.pa_mgr.context, "peak".encode("utf-8"), self.pa_mgr.samplespec, None,
        )
        pa_stream_set_read_callback(self._stream, self._on_stream_read_ctypes, None)
        if self._is_sink_input:
            pa_stream_set_monitor_stream(self._stream, self.idx)
        pa_stream_connect_record(
            self._stream,
            "{:d}".format(self.sink_idx).encode("utf-8"),
            None,
            PA_STREAM_DONT_MOVE | PA_STREAM_PEAK_DETECT | PA_STREAM_ADJUST_LATENCY,
        )

    def stop_monitor_stream(self):
        if self._stream is not None:
            pa_stream_disconnect(self._stream)
            self._stream = None

    def _on_stream_read(self, stream, length, _):
        data = c_void_p()
        pa_stream_peek(stream, data, c_ulong(length))
        data = cast(data, POINTER(c_ubyte))
        # When PA_SAMPLE_U8 is used, samples values range from 128 to 255
        val = sum([data[i] - 128 for i in range(length)]) / length / 128.0
        pa_stream_drop(stream)
        if self._is_sink_input:
            GObject.idle_add(self.pa_mgr.volctl.update_sink_input_peak, self.idx, val)
        else:
            GObject.idle_add(self.pa_mgr.volctl.update_sink_peak, self.idx, val)


class Sink(AbstractMonitorableSink):
    """An audio interface."""

    def __init__(self, pa_mgr, idx, struct, props):
        super().__init__(pa_mgr, idx)
        self.update(struct, props)

    def update(self, struct, props):
        """Update sink values."""
        super().update(struct, props)
        # set values
        self._name = struct.description.decode("utf-8")
        self._sink_name = struct.name
        self._icon_name = "audio-card"
        self.volume = struct.volume.values[0]
        self.channels = struct.volume.channels
        self.mute = bool(struct.mute)

        # notify volctl about update (first sound card)
        if self.pa_mgr.is_main_sink(self._sink_name):
            GObject.idle_add(self.pa_mgr.volctl.update_values, self.volume, self.mute)
        # scale update
        GObject.idle_add(
            self.pa_mgr.volctl.update_sink_scale, self.idx, self.volume, self.mute,
        )

    def set_volume(self, volume):
        """Set volume for this sink."""
        self.volume = volume
        cvolume = cvolume_from_volume(volume, self.channels)
        self.pa_mgr.set_sink_volume(self.idx, cvolume)

    def set_mute(self, mute):
        """Set mute for this sink."""
        self.mute = mute
        self.pa_mgr.set_sink_mute(self.idx, mute and 1 or 0)

    @property
    def sink_name(self):
        """The PA-internal name of the sink"""
        return self._sink_name

class SinkInput(AbstractMonitorableSink):
    """An audio stream coming from a client."""

    def __init__(self, pa_mgr, idx, struct, props):
        self._sink_idx = struct.sink
        super().__init__(pa_mgr, idx)
        self.update(struct, props)

    def update(self, struct, props):
        """Update sink input values."""
        super().update(struct, props)
        self._sink_idx = struct.sink
        self.client = struct.client
        self.app_name = props.get(b"application.name")
        if self.app_name is not None:
            self.app_name = self.app_name.decode("utf-8")
        self.media_name = props.get(b"media.name")
        if self.media_name is not None:
            self.media_name = self.media_name.decode("utf-8")
        self._icon_name = props.get(b"media.icon_name")
        if self._icon_name is None:
            self._icon_name = props.get(b"application.icon_name")
        if self._icon_name is not None:
            self._icon_name = self._icon_name.decode("utf-8")
        GObject.idle_add(
            self.pa_mgr.volctl.update_sink_input_scale,
            self.idx,
            self.volume,
            self.mute,
        )

    def _get_client(self):
        return self.pa_mgr.get_pa_client(self.client)

    def set_volume(self, volume):
        """Set volume for this sink input."""
        self.volume = volume
        cvolume = cvolume_from_volume(volume, self.channels)
        self.pa_mgr.set_sink_input_volume(self.idx, cvolume)

    def set_mute(self, mute):
        """Set mute for this sink input."""
        self.mute = mute
        self.pa_mgr.set_sink_input_mute(self.idx, mute and 1 or 0)

    @property
    def icon_name(self):
        """Sink input icon name"""
        try:
            return self._icon_name
        except AttributeError:
            return self._get_client().icon_name

    @property
    def name(self):
        """Sink input name"""
        try:
            return "{}: {}".format(self.app_name, self.media_name)
        except AttributeError:
            try:
                return self.app_name
            except AttributeError:
                return self._get_client().name

    @property
    def sink_idx(self):
        """Sink index"""
        return self._sink_idx


class Client:
    """Represents an audio emitting application connected to PA."""

    # pylint: disable=too-few-public-methods

    def __init__(self, pa_mgr, idx):
        self.pa_mgr = pa_mgr
        self.idx = idx
        self.name = ""
        self.icon_name = None

    def update(self, struct, props):
        """Update client name and icon."""
        self.name = struct.name.decode("utf-8")
        self.icon_name = props.get(
            b"application.icon_name", b"multimedia-volume-control"
        ).decode("utf-8")
