"""Autoscalers: perform autoscaling by monitoring metrics."""
import bisect
import dataclasses
import enum
import math
import time
import typing
from typing import Any, Callable, Dict, List, Optional, Type, Union

from sky import sky_logging
from sky.serve import constants
from sky.serve import serve_state
from sky.serve import solvers
from sky.serve.serve_utils import AcceleratorType
from sky.utils import env_options

if typing.TYPE_CHECKING:
    from sky.serve import replica_managers
    from sky.serve import service_spec

logger = sky_logging.init_logger(__name__)


class AutoscalerDecisionOperator(enum.Enum):
    SCALE_UP = 'scale_up'
    SCALE_DOWN = 'scale_down'


@dataclasses.dataclass
class AutoscalerDecision:
    """Autoscaling decisions.
    |------------------------------------------------------------------------|
    | Operator   | TargetType                | Meaning                       |
    |------------|---------------------------|-------------------------------|
    | SCALE_UP   | Optional[Dict[str, Any]   | Resource override to add      |
    |------------|---------------------------|-------------------------------|
    | SCALE_DOWN | int                       | Replica id to remove          |
    |------------------------------------------------------------------------|
    """
    operator: AutoscalerDecisionOperator
    target: Union[Optional[Dict[str, Any]], int]

    # TODO(MaoZiming): Add a doc to elaborate on autoscaling policies.
    def __init__(self, operator: AutoscalerDecisionOperator,
                 target: Union[Optional[Dict[str, Any]], int]):

        assert (operator == AutoscalerDecisionOperator.SCALE_UP and
                (target is None or isinstance(target, dict))) or (
                    operator == AutoscalerDecisionOperator.SCALE_DOWN and
                    isinstance(target, int))
        self.operator = operator
        self.target = target

    def __repr__(self) -> str:
        return f'AutoscalerDecision({self.operator}, {self.target})'


class Autoscaler:
    """Abstract class for autoscalers."""

    NAME: Optional[str] = None
    REGISTRY: Dict[str, Type['Autoscaler']] = dict()

    def __init__(self, spec: 'service_spec.SkyServiceSpec') -> None:
        """Initialize the autoscaler.

        Variables:
            min_replicas: Minimum number of replicas.
            max_replicas: Maximum number of replicas. Default to fixed
                number of replicas, i.e. min_replicas == max_replicas.
            target_num_replicas: Target number of replicas output by autoscaler.
        """
        self.min_replicas: int = spec.min_replicas
        self.max_replicas: int = spec.max_replicas or spec.min_replicas
        self.target_num_replicas: int = spec.min_replicas

    def collect_request_information(
            self, request_aggregator_info: Dict[str, Any]) -> None:
        """Collect request information from aggregator for autoscaling."""
        raise NotImplementedError

    def evaluate_scaling(
        self,
        replica_infos: List['replica_managers.ReplicaInfo'],
    ) -> List[AutoscalerDecision]:
        """Evaluate autoscale options based on replica information."""
        raise NotImplementedError

    def __init_subclass__(cls) -> None:
        if cls.NAME is None:
            # This is an abstract class, don't put it in the registry.
            return
        assert cls.NAME not in cls.REGISTRY, f'Name {cls.NAME} already exists'
        cls.REGISTRY[cls.NAME] = cls

    @classmethod
    def get_autoscaler_names(cls) -> List[str]:
        return list(cls.REGISTRY.keys())

    @classmethod
    def from_spec(cls, spec: 'service_spec.SkyServiceSpec') -> 'Autoscaler':
        assert (spec.autoscaler is not None and spec.autoscaler in cls.REGISTRY)
        return cls.REGISTRY[spec.autoscaler](spec)

class RequestRateAutoscaler(Autoscaler):
    """RequestRateAutoscaler: Autoscale according to request rate.

    Scales when the number of requests in the given interval is above or below
    the threshold.
    """
    NAME: Optional[str] = 'RequestRateAutoscaler'

    def __init__(self, spec: 'service_spec.SkyServiceSpec') -> None:
        """Initialize the request rate autoscaler.

        Variables:
            target_qps_per_replica: Target qps per replica for autoscaling.
            request_timestamps: All request timestamps within the window.
            upscale_counter: counter for upscale number of replicas.
            downscale_counter: counter for downscale number of replicas.
            scale_up_consecutive_periods: period for scaling up.
            scale_down_consecutive_periods: period for scaling down.
        """
        super().__init__(spec)
        self.target_qps_per_replica: Optional[
            float] = spec.target_qps_per_replica
        self.request_timestamps: List[float] = []
        self.upscale_counter: int = 0
        self.downscale_counter: int = 0
        self.scale_up_consecutive_periods: int = int(
            spec.upscale_delay_seconds /
            constants.AUTOSCALER_DEFAULT_DECISION_INTERVAL_SECONDS)
        self.scale_down_consecutive_periods: int = int(
            spec.downscale_delay_seconds /
            constants.AUTOSCALER_DEFAULT_DECISION_INTERVAL_SECONDS)
        # Target number of replicas is initialized to min replicas.
        # TODO(MaoZiming): add init replica numbers in SkyServe spec.
        self.target_num_replicas: int = spec.min_replicas
        self.bootstrap_done: bool = False

    def collect_request_information(
            self, request_aggregator_info: Dict[str, Any]) -> None:
        """Collect request information from aggregator for autoscaling.

        request_aggregator_info should be a dict with the following format:

        {
            'timestamps': [timestamp1 (float), timestamp2 (float), ...]
        }
        """
        self.request_timestamps.extend(
            request_aggregator_info.get('timestamps', []))
        current_time = time.time()
        index = bisect.bisect_left(self.request_timestamps,
                                   current_time - constants.AUTOSCALER_QPS_WINDOW_SIZE_SECONDS)
        self.request_timestamps = self.request_timestamps[index:]

    def _get_desired_num_replicas(self) -> int:
        # Always return self.target_num_replicas when autoscaling
        # is not enabled, i.e. self.target_qps_per_replica is None.
        # In this case, self.target_num_replicas will be min_replicas.
        if self.target_qps_per_replica is None:
            return self.target_num_replicas

        # Convert to requests per second.
        num_requests_per_second = len(
            self.request_timestamps) / constants.AUTOSCALER_QPS_WINDOW_SIZE_SECONDS
        target_num_replicas = math.ceil(num_requests_per_second /
                                        self.target_qps_per_replica)
        target_num_replicas = max(self.min_replicas,
                                  min(self.max_replicas, target_num_replicas))
        logger.info(f'Requests per second: {num_requests_per_second}, '
                    f'Current target number of replicas: {target_num_replicas}')

        if not self.bootstrap_done:
            self.bootstrap_done = True
            return target_num_replicas
        elif target_num_replicas > self.target_num_replicas:
            self.upscale_counter += 1
            self.downscale_counter = 0
            if self.upscale_counter >= self.scale_up_consecutive_periods:
                self.upscale_counter = 0
                return target_num_replicas
        elif target_num_replicas < self.target_num_replicas:
            self.downscale_counter += 1
            self.upscale_counter = 0
            if self.downscale_counter >= self.scale_down_consecutive_periods:
                self.downscale_counter = 0
                return target_num_replicas
        else:
            self.upscale_counter = self.downscale_counter = 0
        return self.target_num_replicas

    def evaluate_scaling(
        self,
        replica_infos: List['replica_managers.ReplicaInfo'],
    ) -> List[AutoscalerDecision]:
        """Evaluate Autoscaling decisions based on replica information.
        If the number of launched replicas is less than the target,
        Trigger a scale up. Else, trigger a scale down.

        For future compatibility, we return a list of AutoscalerDecision.
        Scale-up could include both spot and on-demand, each with a resource
        override dict. Active migration could require returning both SCALE_UP
        and SCALE_DOWN.
        """
        launched_replica_infos = [
            info for info in replica_infos if info.is_launched
        ]
        num_launched_replicas = len(launched_replica_infos)

        self.target_num_replicas = self._get_desired_num_replicas()
        logger.info(
            f'Final target number of replicas: {self.target_num_replicas} '
            f'Upscale counter: {self.upscale_counter}/'
            f'{self.scale_up_consecutive_periods}, '
            f'Downscale counter: {self.downscale_counter}/'
            f'{self.scale_down_consecutive_periods} '
            f'Number of launched replicas: {num_launched_replicas}')

        scaling_options = []
        all_replica_ids_to_scale_down: List[int] = []

        def _get_replica_ids_to_scale_down(num_limit: int) -> List[int]:

            status_order = serve_state.ReplicaStatus.scale_down_decision_order()
            launched_replica_infos_sorted = sorted(
                launched_replica_infos,
                key=lambda info: status_order.index(info.status)
                if info.status in status_order else len(status_order))

            return [info.replica_id for info in launched_replica_infos_sorted
                   ][:num_limit]

        if num_launched_replicas < self.target_num_replicas:
            num_replicas_to_scale_up = (self.target_num_replicas -
                                        num_launched_replicas)

            for _ in range(num_replicas_to_scale_up):
                scaling_options.append(
                    AutoscalerDecision(AutoscalerDecisionOperator.SCALE_UP,
                                       target=None))

        elif num_launched_replicas > self.target_num_replicas:
            num_replicas_to_scale_down = (num_launched_replicas -
                                          self.target_num_replicas)
            all_replica_ids_to_scale_down.extend(
                _get_replica_ids_to_scale_down(
                    num_limit=num_replicas_to_scale_down))

        for replica_id in all_replica_ids_to_scale_down:
            scaling_options.append(
                AutoscalerDecision(AutoscalerDecisionOperator.SCALE_DOWN,
                                   target=replica_id))

        if not scaling_options:
            logger.info('No scaling needed.')
        return scaling_options


class HeteroAccelAutoscaler(Autoscaler):
    """RequestRateAutoscaler: Autoscale according to request rate.

    Scales when the number of requests in the given interval is above or below
    the threshold.
    """
    NAME: Optional[str] = 'HeteroAccelAutoscaler'

    SCALE_UP_COOL_DOWN_INTERVAL_SECONDS = 300

    def __init__(self, spec: 'service_spec.SkyServiceSpec',) -> None:
        """Initialize the request rate autoscaler.

        Variables:
            upper_threshold: Upper threshold for scale up. If None, no scale up.
            lower_threshold: Lower threshold for scale down. If None, no scale
                down.
            cooldown: Cooldown between two scaling operations in seconds.
            rps_window_size: Window size for rps calculating.
            last_scale_operation: Time of last scale operation.
            request_timestamps: All request timestamps within the window.
        """
        super().__init__(spec)
        self.rps_window_size: int = self.SCALE_UP_COOL_DOWN_INTERVAL_SECONDS
        self.frequency = constants.AUTOSCALER_DEFAULT_DECISION_INTERVAL_SECONDS
        self.last_scale_operation: float = 0.
        self.request_timestamps_distribution: List[List[float]] = [[], [], [],
                                                                   [], [], [],
                                                                   []]
        self.request_distribution: List[int] = [0, 0, 0, 0, 0, 0, 0]
        self.request_rate_dist: List[float] = [0, 0, 0, 0, 0, 0, 0]
        self.total_request_in_window: int = 0
        self.scale_down_candidates: List['replica_managers.ReplicaInfo'] = []

    def collect_request_information(
            self, request_aggregator_info: Dict[str, Any]) -> None:
        """Collect request information from aggregator for autoscaling.

        request_aggregator_info should be a dict with the following format:

        {
            'timestamps': [timestamp1 (float), timestamp2 (float), ...]
        }
        """
        self.total_request_in_window = 0
        timestamps_from_loadbalancer = request_aggregator_info.get(
            'timestamps', [[], [], [], [], [], [], []])
        current_time = time.time()
        for idx, lst in enumerate(self.request_timestamps_distribution):
            lst.extend(timestamps_from_loadbalancer[idx])
            index = bisect.bisect_left(lst, current_time - self.rps_window_size)
            self.request_timestamps_distribution[idx] = lst[index:]
            self.total_request_in_window += len(self.request_timestamps_distribution[idx])

        if self.total_request_in_window == 0:
            for idx, lst in enumerate(self.request_timestamps_distribution):
                self.request_distribution[idx] = 0
                self.request_rate_dist[idx] = 0
        else:
            for idx, lst in enumerate(self.request_timestamps_distribution):
                self.request_distribution[idx] = len(
                    lst) / self.total_request_in_window
                print(f'autoscaler.collect_request_information(len(lst)): {len(lst)}')
                print(f'autoscaler.collect_request_information(self.total_request_in_window): {self.total_request_in_window}')
                self.request_rate_dist[idx] = len(lst) / self.rps_window_size

                
        # print(
        #     f'autoscaler.collect_request_information(timestamps_from_loadbalancer): {timestamps_from_loadbalancer}'
        # )
        #print(
        #    f'autoscaler.collect_request_information(self.request_timestamps_distribution): {self.request_timestamps_distribution}'
        #)
        print(
            f'autoscaler.collect_request_information(self.total_request_in_window): {self.total_request_in_window}'
        )
        print(
            f'autoscaler.collect_request_information(self.request_distribution): {self.request_distribution}'
        )
        print(
            f'autoscaler.collect_request_information(self.request_rate_dist): {self.request_rate_dist}'
        )

    def _get_accelerator_override_dict(
            self, instance_type: AcceleratorType) -> Dict[str, Any]:
        if instance_type == AcceleratorType.A10:
            return {'accelerators': 'A10G:1'}
        return {'accelerators': f'{instance_type.value}:1'}

    def _get_autoscaler_decision(
            self,
            operator: AutoscalerDecisionOperator,
            accelerator: Optional[AcceleratorType] = None,
            is_primary: Optional[bool] = None,
            replica_id: Optional[int] = None) -> AutoscalerDecision:
        if operator == AutoscalerDecisionOperator.SCALE_UP:
            assert accelerator, accelerator
            operator_target = self._get_accelerator_override_dict(accelerator)
            operator_target.update({
                'is_primary': True if is_primary else False,
                'is_fallback': False if is_primary else True,
            })
            decision = AutoscalerDecision(operator, target=operator_target)
        else:  # SCALE_DOWN
            assert replica_id, replica_id
            decision = AutoscalerDecision(operator, target=replica_id)
        return decision

    def _get_fallback_allocation(self, accelerator: AcceleratorType):
        if accelerator == AcceleratorType.A10:
            num, fallback_type = 0, None
        elif accelerator == AcceleratorType.A100:
            num, fallback_type = 4, AcceleratorType.A10
        return num, fallback_type

    def fallback_scale_down_sync(
        self,
        service_name: str,
        replica_manager: 'replica_managers.ReplicaManager',
    ) -> None:
        replica_infos = serve_state.get_replica_infos(service_name)
        replica_info_dicts = [
            info.to_info_dict(
                with_handle=env_options.Options.SHOW_DEBUG_INFO.get())
            for info in replica_infos
        ]
        logger.info(
            f'All replica info before fallback sync: {replica_info_dicts}')
        # Iterate through replica_infos and check for primary replicas
        # Check if each primary replica in state of ReplicaStatus.READY
        # has existing fallback replicas
        ready_primary_replica_infos = [
            info for info in replica_infos if info.is_primary and
            info.is_ready and info.fallback_replica_id_list
        ]
        ready_replica_info_dicts = [
            info.to_info_dict(
                with_handle=env_options.Options.SHOW_DEBUG_INFO.get())
            for info in ready_primary_replica_infos
        ]
        logger.info(f'fallback_scale_down_sync(ready_primary_replica_infos): {ready_replica_info_dicts}')
        for info in ready_primary_replica_infos:
            fallback_replica_id_to_terminate = info.fallback_replica_id_list
            logger.info(f'fallback_scale_down_sync(fallback_replica_id_to_terminate): {fallback_replica_id_to_terminate}')
            for replica_id in fallback_replica_id_to_terminate:
                logger.info(f'fallback_scale_down_sync(before replica_id): {replica_id}')
                replica_manager.scale_down(replica_id)
                info.fallback_replica_id_list.remove(replica_id)
                serve_state.add_or_update_replica(service_name, info.replica_id,
                                                  info)
                logger.info(f'fallback_scale_down_sync(after replica_id): {replica_id}')


    def in_scale_down_candidates(self, replica_id: int):
        for info in self.scale_down_candidates:
            if info.replica_id == replica_id:
                return True
        return False

    def filter_scale_down_candidates(self,
                                     accelerator_type: AcceleratorType,
                                     max_num: Optional[int] = None):
        # Removes the 'accelerator_type' infos from the scale_down_candidates
        # If 'max_num' is provided, it filters out only 'max_num' number of
        # 'accelerator_type' infos from the scale_down_candidates and the rest
        # remains.
        if max_num is None:
            return [info for info in self.scale_down_candidates
                    if info.accelerator != accelerator_type]

        cnt = 0
        tmp_scale_down_candidates = []
        for info in self.scale_down_candidates:
            if info.accelerator == accelerator_type:
                if cnt < max_num:
                    cnt += 1
                    continue
            tmp_scale_down_candidates.append(info)
        return tmp_scale_down_candidates[:]

    def evaluate_scaling(
        self,
        replica_infos: List['replica_managers.ReplicaInfo'],
    ) -> List[Union[AutoscalerDecision, List[AutoscalerDecision]]]:
        ##### Testing
        accel_allocation = solvers.IlpSolver(self.request_rate_dist)
        logger.info(f'evaluate_scaling(self.request_rate_dist): {self.request_rate_dist}')
        logger.info(f'evaluate_scaling(accel_allocation): A10:{accel_allocation[AcceleratorType.A10]}')
        logger.info(f'evaluate_scaling(accel_allocation): A100:{accel_allocation[AcceleratorType.A100]}')
        logger.info('TESTING solver output')
        #############
        all_replica_infos_to_scale_down: List[
            'replica_managers.ReplicaInfo'] = []
        scaling_decisions: (List[Union[AutoscalerDecision,
                                       List[AutoscalerDecision]]]) = []
        
        # Return if the cool down interval has not passed. 
        if (time.time()- self.last_scale_operation < 
            self.SCALE_UP_COOL_DOWN_INTERVAL_SECONDS):
            return scaling_decisions

        self.last_scale_operation = time.time()
        launched_replica_infos = [
            info for info in replica_infos if info.is_launched
        ]
        logger.info(f'evaluate_scaling(launched_replica_infos): {launched_replica_infos}')
        def _get_replica_infos_to_scale_down(
            info_filter: Callable[['replica_managers.ReplicaInfo'], bool],
            status_order: List['serve_state.ReplicaStatus'],
            num_limit: int,
        ) -> List[int]:
            replica_infos_to_scale_down: List[int] = []
            for target_status in status_order:
                for info in launched_replica_infos:
                    if info_filter(info) and info.status == target_status:
                        if len(replica_infos_to_scale_down) >= num_limit:
                            return replica_infos_to_scale_down
                        replica_infos_to_scale_down.append(info)
            for info in launched_replica_infos:
                if info_filter(info) and info.status not in status_order:
                    if len(replica_infos_to_scale_down) >= num_limit:
                        return replica_infos_to_scale_down
                    replica_infos_to_scale_down.append(info)
            return replica_infos_to_scale_down

        # Pass the histogram to solver and get the ideal GPU allocation. Assume
        # the allocation to be a dictionary in a form of
        # {replica_manager.AcceleratorType.A100: # of A100s needed,
        #  replica_manager.AcceleratorType.A10: # of A10s needed}
        accel_allocation = solvers.IlpSolver(self.request_rate_dist)
        logger.info(f'evaluate_scaling(self.request_rate_dist): {self.request_rate_dist}')
        logger.info(f'evaluate_scaling(accel_allocation): A10:{accel_allocation[AcceleratorType.A10]}')
        logger.info(f'evaluate_scaling(accel_allocation): A100:{accel_allocation[AcceleratorType.A100]}')
        logger.info('ACTUAL solver output after cooldown period')

        # Compare the nubmers from GPU allocation and replica infos to get what needs to be scaled up/down
        # return a list of AutoscalerDecisions
        for accelerator_type in [AcceleratorType.A10, AcceleratorType.A100]:
            num_alive_accel = len([
                info for info in launched_replica_infos
                if info.accelerator == accelerator_type and info.is_primary
            ])
            
            alive_accel = [
                info for info in launched_replica_infos
                if info.accelerator == accelerator_type and info.is_primary
            ]
            alive_accel_dict = [
                info.to_info_dict(
                    with_handle=env_options.Options.SHOW_DEBUG_INFO.get())
                for info in alive_accel
            ]
            logger.info(f'evaluate_scaling(alive_accel_dict): {alive_accel_dict}')
            
            num_scale_down_candidate = len([
                info for info in self.scale_down_candidates
                if info.accelerator == accelerator_type
            ])
            logger.info(f'evaluate_scaling(num_scale_down_candidate): {num_scale_down_candidate}')
            if accelerator_type in accel_allocation: # and accel_allocation[accelerator_type] > 0: Setting this > 0 condition made impossible to enther this condition when accelerator was allocated to 0.
                diff_accel_num = num_alive_accel - accel_allocation[accelerator_type]
                logger.info(f'evaluate_scaling(diff_accel_num): {diff_accel_num}')
                # Need to clear scale_down_candidates
                if diff_accel_num == 0:
                    if num_scale_down_candidate > 0:
                        # remove all the 'accelerator_type' infos from the
                        # scale_down_candidates list. This is necessary since
                        # it's determined at this interval that we need to keep
                        # the number of replicas for this accelerator type.
                        self.scale_down_candidates = self.filter_scale_down_candidates(accelerator_type)
                        logger.info('evaluate_scaling(1)')
                        [info for info in self.scale_down_candidates if info.accelerator != accelerator_type]
                # Need to scale up
                elif diff_accel_num < 0:
                    num_to_scale_up = int(abs(diff_accel_num))
                    for _ in range(num_to_scale_up):
                        num, fallback_type = self._get_fallback_allocation(
                            accelerator_type)
                        # Setting up to launch fallback replicas along with
                        # primary replica
                        if num > 0:
                            logger.info('evaluate_scaling(2-1)')
                            primary_fallback_decisions = []
                            for _ in range(num):
                                fallback_decision = self._get_autoscaler_decision(
                                    AutoscalerDecisionOperator.SCALE_UP,
                                    accelerator=fallback_type,
                                    is_primary=False)
                                primary_fallback_decisions.append(
                                    fallback_decision)
                            primary_decision = self._get_autoscaler_decision(
                                AutoscalerDecisionOperator.SCALE_UP,
                                accelerator=accelerator_type,
                                is_primary=True)
                            primary_fallback_decisions.append(primary_decision)
                            scaling_decisions.append(primary_fallback_decisions)
                        # There is no fallback replica to be launched for the
                        # accelerator type
                        else:
                            logger.info('evaluate_scaling(2-2)')
                            decision = self._get_autoscaler_decision(
                                AutoscalerDecisionOperator.SCALE_UP,
                                accelerator=accelerator_type,
                                is_primary=True)
                            scaling_decisions.append(decision)
                    logger.info(f'evaluate_scaling(2)(scaling_decisions): {scaling_decisions}')
                    # Remove all the 'accelerator_type' replicas from 
                    # scale_down_candidates list. This is necessary as it is 
                    # determined at this interval that this accelerator type
                    # needs to be scaled up and not down.
                    self.scale_down_candidates = self.filter_scale_down_candidates(accelerator_type)
                # Need to scale down
                elif diff_accel_num > 0:
                    extra_scale_down_num = diff_accel_num - num_scale_down_candidate
                    # Nothing to be done when extra_scale_down_num == 0
                    # Need to scale down replicas in addition to the ones
                    # already in the scale_down_candidates list
                    if extra_scale_down_num > 0:
                        logger.info('evaluate_scaling(3-1)')
                        all_replica_infos_to_scale_down.extend(
                            _get_replica_infos_to_scale_down(
                                info_filter=lambda info: info.accelerator ==
                                accelerator_type and info.is_primary and
                                not self.in_scale_down_candidates(info.replica_id),
                                status_order=serve_state.ReplicaStatus.
                                scale_down_decision_order(),
                                num_limit=extra_scale_down_num,
                            ))
                    # Reduce the number of replicas from scale_down_candidate
                    # list. It is determined in this interval by the solver
                    # that the number of replicas to be scaled down are less
                    # than what is determined from the previous interval.
                    elif extra_scale_down_num < 0:
                        self.scale_down_candidates = self.filter_scale_down_candidates(
                            accelerator_type,
                            max_num=abs(extra_scale_down_num))
                        logger.info('evaluate_scaling(3-2)')
        
                all_replica_infos_to_scale_down_dicts = [
                    info.to_info_dict(
                        with_handle=env_options.Options.SHOW_DEBUG_INFO.get())
                    for info in all_replica_infos_to_scale_down
                ]
        logger.info(f'evaluate_scaling(all_replica_infos_to_scale_down_dicts): {all_replica_infos_to_scale_down_dicts}')

        # Need to make sure to put down the fallback replicas
        # if the primary replica is set to be down.
        # Note: We scale down the replica candidates from the previous
        # call the evaluate_scaling. This allows a delayed scale down
        # operation mitigating the time discrepancy occurring by the time taken
        # to launch with scale up operation.
        scale_down_candidates_dicts = [
            info.to_info_dict(
                with_handle=env_options.Options.SHOW_DEBUG_INFO.get())
            for info in self.scale_down_candidates
        ]
        logger.info(f'Before evaluate_scaling(scale_down_candidates_dicts): {scale_down_candidates_dicts}')
        for info in self.scale_down_candidates:
            decision = self._get_autoscaler_decision(
                AutoscalerDecisionOperator.SCALE_DOWN,
                replica_id=info.replica_id)
            scaling_decisions.append(decision)
            if info.fallback_replica_id_list is not None:
                for replica_id in info.fallback_replica_id_list:
                    decision = self._get_autoscaler_decision(
                        AutoscalerDecisionOperator.SCALE_DOWN,
                        replica_id=replica_id)
                    logger.info(f'evaluate_scaling(info): {info}')
                    logger.info(f'evaluate_scaling(info.fallback_replica_id_list): {info.fallback_replica_id_list}')
                    scaling_decisions.append(decision)

        # The replicas being terminated this interval should not be added
        # to the scale down candidate list. This sifting is necessary as the
        # solver may output the same GPU allocation as the previous interval
        # which results into a same output to all_replica_infos_to_scale_down
        # from the previous interval.
        down_set = set()
        for decision in scaling_decisions:
            if (not isinstance(decision, list) and
                decision.operator == AutoscalerDecisionOperator.SCALE_DOWN):
                down_set.add(decision.target)
        logger.info(f'evaluate_scaling(down_set): {down_set}')
        self.scale_down_candidates = []
        for info in all_replica_infos_to_scale_down:
            if info.replica_id not in down_set:
                self.scale_down_candidates.append(info)

        scale_down_candidates_dicts = [
            info.to_info_dict(
                with_handle=env_options.Options.SHOW_DEBUG_INFO.get())
            for info in self.scale_down_candidates
        ]
        logger.info(f'After evaluate_scaling(scale_down_candidates_dicts): {scale_down_candidates_dicts}')
        
        if not scaling_decisions:
            logger.info('No scaling needed.')
        logger.info(f'evaluate_scaling(scaling_decisions): {scaling_decisions}')
        return scaling_decisions
