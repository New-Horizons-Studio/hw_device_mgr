from ..device import Device, SimDevice
from ..data_types import DataType
from ..config_io import ConfigIO
from functools import lru_cache


class ErrorDevice(Device, ConfigIO):
    """
    Abstract class representing a device error code handling.

    Error code is fed into `error_code` feedback.

    The `set_feedback()` method looks up the error code in the
    `device_err/{name}.yaml` file and adds `description` and `advice`
    strings to feedback.
    """

    device_error_package = None
    device_error_yaml = None

    feedback_in_data_types = dict(error_code="uint32")
    feedback_in_defaults = dict(error_code=0)

    feedback_out_defaults = dict(
        error_code=0, description="No error", advice="No error"
    )
    feedback_out_data_types = dict(
        error_code="uint32", description="str", advice="str"
    )

    no_error = feedback_out_defaults

    data_type_class = DataType

    _error_descriptions = dict()

    @classmethod
    @lru_cache
    def error_descriptions(cls):
        """
        Return dictionary of error code data.

        Data is read from YAML resource from package
        `device_error_package`, name `device_error_yaml`.
        """
        errs = dict()
        assert cls.device_error_yaml, f"{cls} has no device_error_yaml"
        if cls.device_error_yaml:
            err_yaml = cls.load_yaml_resource(
                cls.device_error_package, cls.device_error_yaml
            )
            for err_code_str, err_data in err_yaml.items():
                errs[int(err_code_str, 0)] = err_data
        return errs

    def get_feedback(self):
        fb_out = super().get_feedback()
        error_code = self.feedback_in.get("error_code")
        if not error_code:
            self.feedback_out.update(**self.no_error)
            return fb_out

        error_info = self.error_descriptions().get(error_code, None)
        if error_info is None:
            error_info = dict(
                description=f"Unknown error code {error_code}",
                advice="Contact technical support",
            )
        fb_out.update(error_code=error_code, **error_info)
        if fb_out.changed("error_code"):
            desc = error_info["description"]
            msg = f"{str(self)}:  error code {error_code}:  {desc}"
            self.logger.error(msg)
        return fb_out


class ErrorSimDevice(ErrorDevice, SimDevice):
    """Abstract class representing a device simulated error code handling."""
