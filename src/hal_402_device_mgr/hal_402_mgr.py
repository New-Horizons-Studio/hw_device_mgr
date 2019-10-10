# -*- coding: utf-8 -*-
import rospy
import time
import hal
import attr
from fysom import Fysom, FysomError

# import service messages from the ROS node
from hal_402_device_mgr.srv import srv_robot_state
from hal_402_device_mgr.hal_402_drive import (
    Drive402,
    GenericHalPin,
    StateMachine402,
)


@attr.s
class TransitionItem(object):
    name = attr.ib()
    value = attr.ib()
    transition_cb = attr.ib()


class Hal402Mgr(object):
    def __init__(self):
        # Configure sim mode if SIM environment variable is set
        self.sim = rospy.get_param("/sim_mode", True)
        self.compname = 'hal_402_mgr'
        self.drives = dict()
        self.fsm = Fysom(
            {
                'initial': {'state': 'initial', 'event': 'init', 'defer': True},
                'events': [
                    {
                        'name': 'stop',
                        'src': ['initial', 'fault', 'enabled'],
                        'dst': 'stopping',
                    },
                    {'name': 'started', 'src': 'starting', 'dst': 'enabled'},
                    {'name': 'start', 'src': 'disabled', 'dst': 'starting'},
                    {'name': 'stopped', 'src': 'stopping', 'dst': 'disabled'},
                    {
                        'name': 'error',
                        'src': [
                            'initial',
                            'starting',
                            'enabled',
                            'stopping',
                            'disabled',
                        ],
                        'dst': 'fault',
                    },
                ],
                'callbacks': {
                    'oninitial': self.fsm_in_initial,
                    'onstopping': self.fsm_in_stopping,
                    'onstarting': self.fsm_in_starting,
                    'ondisabled': self.fsm_in_disabled,
                    'onenabled': self.fsm_in_enabled,
                    'onfault': self.fsm_in_fault,
                },
            }
        )
        self.prev_hal_transition_cmd = -2
        self.curr_hal_transition_cmd = -2
        self.curr_hal_reset_pin = 0
        self.curr_hal_reset_pin = 0

        self.transitions = {
            'stop': TransitionItem(
                name='stop', value=0, transition_cb=self.fsm.stop
            ),
            'start': TransitionItem(
                name='start', value=1, transition_cb=self.fsm.start
            ),
            'error': TransitionItem(
                name='error', value=2, transition_cb=self.fsm.error
            ),
            'started': TransitionItem(
                name='started', value=3, transition_cb=self.fsm.started
            ),
            'stopped': TransitionItem(
                name='stopped', value=4, transition_cb=self.fsm.stopped
            ),
        }
        self.pins = {
            # Pins used by this component to call the service callbacks
            'state-cmd': GenericHalPin(
                '%s.state-cmd' % self.compname, hal.HAL_IN, hal.HAL_U32
            ),
            'state-fb': GenericHalPin(
                '%s.state-fb' % self.compname, hal.HAL_OUT, hal.HAL_S32
            ),
            'reset': GenericHalPin(
                '%s.reset' % self.compname, hal.HAL_IN, hal.HAL_BIT
            ),
        }
        self.conv_value_to_state = {
            3: 'initial',
            2: 'fault',
            0: 'disabled',
            1: 'enabled',
            4: 'stopping',
            5: 'starting',
        }
        # create ROS node
        rospy.init_node(self.compname)
        rospy.loginfo("%s: Node started" % self.compname)

        # create HAL userland component
        self.halcomp = hal.component(self.compname)
        rospy.loginfo("%s: HAL component created" % self.compname)

        # read in the error list from parameters
        self.read_device_error_list()
        # create drives which create pins
        self.create_drives()
        # create pins for calling service callback
        self.create_pins()

        # check if we're running real hardware, and set up sim state if
        # applicable
        self.check_for_real_hardware_setup()

        self.get_update_rate()
        self.create_service()
        self.create_publisher()

        # done
        self.halcomp.ready()
        self.fsm.init()

    def has_parameters(self, list_of_parameters):
        has_parameters = True
        for parameter in list_of_parameters:
            has_parameters = rospy.has_param(parameter)
            if has_parameters is False:
                # exit this list at first missing parameter
                break
        return has_parameters

    def check_for_real_hardware_setup(self):
        if self.sim:
            self.sim_set_drives_status('SWITCH ON DISABLED')
            rospy.loginfo(
                "%s: no hardware setup detected, default to "
                "simulation mode" % self.compname
            )
        else:
            # Configure real hardware mode
            rospy.loginfo("%s: hardware setup detected" % self.compname)

    def read_device_error_list(self):
        if self.has_parameters(['/device_error_code_list']):
            self.devices_error_list = rospy.get_param('/device_error_code_list')
        else:
            rospy.logerr(
                "%s: no /device_error_code_list params" % self.compname
            )

    def create_drives(self):
        if self.has_parameters(
            [
                '/hal_402_device_mgr/drives/name',
                '/hal_402_device_mgr/drives/instances',
                '/hal_402_device_mgr/drives/types',
                '/hal_402_device_mgr/slaves/instances',
            ]
        ):
            name = rospy.get_param('/hal_402_device_mgr/drives/name')
            drive_instances = rospy.get_param(
                '/hal_402_device_mgr/drives/instances'
            )
            slave_instances = rospy.get_param(
                '/hal_402_device_mgr/slaves/instances'
            )
            drive_types = rospy.get_param('/hal_402_device_mgr/drives/types')
            # sanity check
            if (len(slave_instances) != len(drive_instances)) or (
                len(drive_types) != len(drive_instances)
            ):
                rospy.logerr(
                    "%s: nr of drive and slave instances or drive types do not match"
                    % self.compname
                )
            else:
                for i in range(0, len(drive_instances)):
                    # create n drives from ROS parameters
                    drive_name = name + "_%s" % drive_instances[i]
                    slave_inst = slave_instances[i]
                    drive_type = drive_types[i]
                    self.drives[drive_name] = Drive402(
                        drive_name=drive_name,
                        drive_type=drive_type,
                        parent=self,
                        slave_inst=slave_inst,
                    )
                    rospy.loginfo(
                        "%s: %s created" % (self.compname, drive_name)
                    )
        else:
            rospy.logerr(
                "%s: no correct /hal_402_device_mgr/drives params"
                % self.compname
            )

    def create_pins(self):
        for key, pin in self.pins.items():
            pin.set_parent_comp(self.halcomp)
            pin.create_halpin()

    def get_update_rate(self):
        has_update_rate = rospy.has_param('/hal_402_device_mgr/update_rate')
        if has_update_rate:
            self.update_rate = rospy.get_param(
                '/hal_402_device_mgr/update_rate'
            )
            self.rate = rospy.Rate(self.update_rate)
        else:
            rospy.logerr(
                "%s: no /hal_402_device_mgr/update_rate param found"
                % self.compname
            )

    def get_error_info(self, devicetype, error_code):
        try:
            device_errors = self.devices_error_list[devicetype]['errors']
            info = device_errors[error_code]
            return info
        except KeyError:
            # return a dict
            return {
                'description': 'This error is an unknown error.',
                'solution': 'Please contact your hardware support department.',
            }

    def create_publisher(self):
        # create publishers for topics and send out a test message
        for key, drive in self.drives.items():
            drive.create_topics()
            if drive.sim is True:
                drive.test_publisher()

    def all_drives_are_status(self, status):
        # check if all the drives have the same status
        for key, drive in self.drives.items():
            if not (drive.curr_state == status):
                return False
        return True

    def all_drives_are_not_status(self, status):
        # check if all the drives have a status other than 'status' argument
        for key, drive in self.drives.items():
            if drive.curr_state == status:
                return False
        return True

    def one_drive_has_status(self, status):
        # check if all the drives have the same status
        for key, drive in self.drives.items():
            if drive.curr_state == status:
                return True
        return False

    def sim_set_drives_status(self, status):
        for key, drive in self.drives.items():
            drive.sim_set_status(status)

    def cb_robot_state_service(self, req):
        # The service callback
        # the requested transition is in req.req_transition (string)
        # the return value for the service response (string) is a message
        # check the requested state for validity
        if req.req_transition not in self.transitions:
            rospy.loginfo(
                "%s: request failed, %s not a valid transition"
                % (self.compname, req.req_transition)
            )
            return "%s: request failed, %s not a valid transition" % (
                self.compname,
                req.req_transition,
            )
        else:
            return self.execute_transition(req.req_transition)

    def execute_transition(self, transition):
        try:
            f = self.transitions[transition].transition_cb
            f()
            return (
                "Transition properly executed, current state \'%s\'"
                % self.fsm.current
            )
        except FysomError:
            rospy.logwarn(
                "%s: Transition not possible from state \'%s\', with transition \'%s\'"
                % (self.compname, self.fsm.current, transition)
            )
            return (
                "Transition not possible from state \'%s\', with transition \'%s\'"
                % (self.fsm.current, transition)
            )

    # enter state callbacks
    def fsm_in_initial(self, e=None):
        # print('in_initial')
        self.update_hal_state_fb()

    def fsm_in_disabled(self, e=None):
        self.update_hal_state_fb()

    def change_drives(self, target_path, target_name):
        self.update_hal_state_fb()
        if self.process_drive_transitions(target_path, target_name):
            return True
        else:
            return False

    def fsm_in_stopping(self, e=None):
        target_path = StateMachine402.path_to_switch_on_disabled
        target_name = 'SWITCH ON DISABLED'
        self.update_hal_state_fb()
        if self.change_drives(target_path, target_name):
            self.execute_transition('stopped')
        else:
            self.execute_transition('error')

    def fsm_in_starting(self, e=None):
        target_path = StateMachine402.path_to_operation_enabled
        target_name = 'OPERATION ENABLED'
        self.update_hal_state_fb()
        if self.change_drives(target_path, target_name):
            self.execute_transition('started')
        else:
            self.execute_transition('error')

    def fsm_in_enabled(self, e=None):
        self.update_hal_state_fb()

    def fsm_in_fault(self, e=None):
        # first try to shut down all the drives, if they are not already off
        # thru the HAL plumbing (quick-stop bit should be low at the moment
        # one of the drive faults).
        target_path = StateMachine402.path_to_switch_on_disabled
        target_name = 'SWITCH ON DISABLED'
        self.change_drives(target_path, target_name)
        rospy.logerr(
            "%s: The machine entered \'fault\' state, previous state was \'%s\'"
            % (self.compname, e.src)
        )
        self.update_hal_state_fb()

    # make sure we mirror the state in the halpin
    # convert state to number
    def update_hal_state_fb(self):
        for key, val in self.conv_value_to_state.items():
            if val == self.fsm.current:
                state_nr = key
                self.pins['state-fb'].set_local_value(state_nr)
                self.pins['state-fb'].set_hal_value()

    def process_drive_transitions(self, transition_table, target_states):
        max_retries = 15
        retries = 0
        no_error = True
        for key, drive in self.drives.items():
            # pick a transition table for the requested state
            drive.set_transition_table(transition_table)
            if drive.curr_state != target_states:
                while (not drive.is_transitionable(target_states)) and (
                    retries < max_retries
                ):
                    # if a drive is not ready (startup) wait a bit
                    time.sleep(0.5)
                    self.update_drive_states()
                    retries += 1
                if retries == max_retries:
                    rospy.logerr(
                        "%s: %s needed %i retries, did not get out of state %s"
                        % (
                            self.compname,
                            drive.drive_name,
                            retries,
                            drive.curr_state,
                        )
                    )
                    # this drive has a glitch, continue to next drive
                    no_error = False
                    break
                # no problems so far, so transition until finished
                # max out just in case
                retries = 0
                while (retries < max_retries) and (
                    drive.curr_state != target_states
                ):
                    if not drive.next_transition():
                        # no success, retry please
                        retries += 1
                    self.update_drive_states()
                if drive.curr_state != target_states:
                    rospy.loginfo(
                        "%s: %s did not reach target state after %i retries from state %s"
                        % (
                            self.compname,
                            drive.drive_name,
                            retries,
                            drive.curr_state,
                        )
                    )
                    no_error = False
            self.update_drive_states()
            self.publish_states()
        return no_error

    def create_service(self):
        # $ rosservice call rosservice call /hal_402_drives_mgr "req_transition: ''"
        # will call the function callback, that will receive the service message
        # as an argument. The transition should be added between the single quotes.

        self.service = rospy.Service(
            'hal_402_drives_mgr', srv_robot_state, self.cb_robot_state_service
        )
        rospy.loginfo(
            "%s: service %s created"
            % (self.compname, self.service.resolved_name)
        )

    def update_drive_states(self):
        for key, drive in self.drives.items():
            drive.update_state()

        # get the status pins, and save their value locally
        self.prev_hal_transition_cmd = self.curr_hal_transition_cmd
        self.prev_hal_reset_pin = self.curr_hal_reset_pin
        for key, pin in self.pins.items():
            if pin.dir == hal.HAL_IN:
                pin.sync_hal()
        self.curr_hal_transition_cmd = self.pins['state-cmd'].local_pin_value
        self.curr_hal_reset_pin = self.pins['reset'].local_pin_value

    def transition_from_hal(self):
        # get check if the HAL number is one of the transition numbers
        nr_known = False
        for key, transition in self.transitions.items():
            if transition.value == self.curr_hal_transition_cmd:
                nr_known = True
                transition_name = key
                break
        if not nr_known:
            rospy.loginfo(
                "%s: HAL request failed, %s not a valid transition"
                % (self.compname, self.curr_hal_transition_cmd)
            )
            return "%s: HAL request failed, %s not a valid transition" % (
                self.compname,
                self.curr_hal_transition_cmd,
            )
        else:
            self.execute_transition(transition_name)

    def hal_UI_cmd(self):
        if self.transition_cmd_changed():
            self.transition_from_hal()
        if self.reset_pin_changed():
            # check if we're in disabled state, and if the reset button has
            # rising edge, invoke transition to current transition cmd
            # prevent acting on reset button change from all other states.
            if (self.curr_hal_reset_pin is True) and (
                self.fsm.current == 'disabled'
            ):
                self.transition_from_hal()

    def transition_cmd_changed(self):
        if not (self.prev_hal_transition_cmd == self.curr_hal_transition_cmd):
            return True
        else:
            return False

    def reset_pin_changed(self):
        if not (self.prev_hal_reset_pin == self.curr_hal_reset_pin):
            return True
        else:
            return False

    def manage_errors(self):
        # when in a certain state, we need to check things so we can initiate
        # a transition to an error state for example
        one_drive_faulted = self.one_drive_has_status('FAULT')
        all_drives_operational = self.all_drives_are_status('OPERATION ENABLED')
        if self.fsm.current != 'fault':
            if one_drive_faulted:
                self.execute_transition('error')
        if self.fsm.current == 'enabled':
            if not all_drives_operational:
                self.execute_transition('error')
        if self.fsm.current == 'fault':
            if self.reset_pin_changed() and (self.curr_hal_reset_pin is False):
                # this will get us in the disabled state again, ready for enabling
                self.execute_transition('stop')

    def publish_states(self):
        for key, drive in self.drives.items():
            drive.publish_state()

    def publish_errors(self):
        for key, drive in self.drives.items():
            drive.publish_error()

    def run(self):
        while not rospy.is_shutdown():
            self.update_drive_states()
            self.manage_errors()
            self.hal_UI_cmd()
            self.rate.sleep()
