# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
"""ModelTrainer class module."""
from __future__ import absolute_import

import os
import json
import shutil
from tempfile import TemporaryDirectory

from typing import Optional, List, Union, Dict, Any
from sagemaker_core.main import resources
from sagemaker_core.resources import TrainingJob
from sagemaker_core.shapes import AlgorithmSpecification

from pydantic import BaseModel, ConfigDict, PrivateAttr, validate_call

from sagemaker import get_execution_role, Session
from sagemaker.modules.configs import (
    Compute,
    StoppingCondition,
    RetryStrategy,
    OutputDataConfig,
    SourceCode,
    TrainingImageConfig,
    Channel,
    DataSource,
    S3DataSource,
    FileSystemDataSource,
    Networking,
    Tag,
    MetricDefinition,
    DebugHookConfig,
    DebugRuleConfiguration,
    ExperimentConfig,
    InfraCheckConfig,
    ProfilerConfig,
    ProfilerRuleConfiguration,
    RemoteDebugConfig,
    SessionChainingConfig,
    TensorBoardOutputConfig,
    CheckpointConfig,
    InputData,
)

from sagemaker.modules.distributed import (
    DistributedRunner,
    TorchrunSMP,
)
from sagemaker.modules.utils import (
    _get_repo_name_from_image,
    _get_unique_name,
    _is_valid_path,
    _is_valid_s3_uri,
    safe_serialize,
)
from sagemaker.modules.types import DataSourceType
from sagemaker.modules.constants import (
    DEFAULT_INSTANCE_TYPE,
    SM_CODE,
    SM_CODE_CONTAINER_PATH,
    SM_DRIVERS,
    SM_DRIVERS_LOCAL_PATH,
    TRAIN_SCRIPT,
    DEFAULT_CONTAINER_ENTRYPOINT,
    DEFAULT_CONTAINER_ARGUMENTS,
    SOURCE_CODE_JSON,
    DISTRIBUTED_RUNNER_JSON,
)
from sagemaker.modules.templates import (
    TRAIN_SCRIPT_TEMPLATE,
    EXECUTE_BASE_COMMANDS,
    EXECUTE_MPI_DRIVER,
    EXEUCTE_TORCHRUN_DRIVER,
    EXECUTE_BASIC_SCRIPT_DRIVER,
)
from sagemaker.modules import logger


class ModelTrainer(BaseModel):
    """Class that trains a model using AWS SageMaker.

    Example:
    ```python
    from sagemaker.modules.train import ModelTrainer
    from sagemaker.modules.configs import SourceCode, Compute, InputData

    source_code = SourceCode(source_dir="source", entry_script="train.py")
    training_image = "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-training-image"
    model_trainer = ModelTrainer(
        training_image=training_image,
        source_code=source_code,
    )

    train_data = InputData(channel_name="train", data_source="s3://bucket/train")
    model_trainer.train(input_data_config=[train_data])
    ```

    Attributes:
        session (Optiona(Session)):
            The SageMaker session.
            If not specified, a new session will be created.
        role (Optional(str)):
            The IAM role ARN for the training job.
            If not specified, the default SageMaker execution role will be used.
        base_job_name (Optional[str]):
            The base name for the training job.
            If not specified, a default name will be generated using the algorithm name
            or training image.
        source_code (Optional[SourceCode]):
            The source code configuration. This is used to configure the source code for
            running the training job.
        distributed_runner (Optional[DistributedRunner]):
            The distributed runner for the training job. This is used to configure
            a distributed training job. If specifed, `source_code` must also
            be provided.
        compute (Optional[Compute]):
            The compute configuration. This is used to specify the compute resources for
            the training job. If not specified, will default to 1 instance of ml.m5.xlarge.
        networking (Optional[Networking]):
            The networking configuration. This is used to specify the networking settings
            for the training job.
        stopping_condition (Optional[StoppingCondition]):
            The stopping condition. This is used to specify the different stopping
            conditions for the training job.
            If not specified, will default to 1 hour max run time.
        algorithm_name (Optional[str]):
            The SageMaker marketplace algorithm name/arn to use for the training job.
            algorithm_name cannot be specified if training_image is specified.
        training_image (Optional[str]):
            The training image URI to use for the training job container.
            training_image cannot be specified if algorithm_name is specified.
            To find available sagemaker distributed images,
            see: https://docs.aws.amazon.com/sagemaker/latest/dg-ecr-paths/sagemaker-algo-docker-registry-paths
        training_image_config (Optional[TrainingImageConfig]):
            Training image Config. This is the configuration to use an image from a private
            Docker registry for a traininob.
        output_data_config (Optional[OutputDataConfig]):
            The output data configuration. This is used to specify the output data location
            for the training job.
            If not specified, will default to `s3://<default_bucket>/<base_job_name>/output/`.
        input_data_config (Optional[List[Union[Channel, InputData]]]):
            The input data config for the training job.
            Takes a list of Channel or InputData objects. An InputDataSource can be an S3 URI
            string, local file path string, S3DataSource object, or FileSystemDataSource object.
        checkpoint_config (Optional[CheckpointConfig]):
            Contains information about the output location for managed spot training checkpoint
            data.
        training_input_mode (Optional[str]):
            The input mode for the training job. Valid values are "Pipe", "File", "FastFile".
            Defaults to "File".
        environment (Optional[Dict[str, str]]):
            The environment variables for the training job.
        hyperparameters (Optional[Dict[str, Any]]):
            The hyperparameters for the training job.
        tags (Optional[List[Tag]]):
            An array of key-value pairs. You can use tags to categorize your AWS resources
            in different ways, for example, by purpose, owner, or environment.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    session: Optional[Session] = None
    role: Optional[str] = None
    base_job_name: Optional[str] = None
    source_code: Optional[SourceCode] = None
    distributed_runner: Optional[DistributedRunner] = None
    compute: Optional[Compute] = None
    networking: Optional[Networking] = None
    stopping_condition: Optional[StoppingCondition] = None
    training_image: Optional[str] = None
    training_image_config: Optional[TrainingImageConfig] = None
    algorithm_name: Optional[str] = None
    output_data_config: Optional[OutputDataConfig] = None
    input_data_config: Optional[List[Union[Channel, InputData]]] = None
    checkpoint_config: Optional[CheckpointConfig] = None
    training_input_mode: Optional[str] = "File"
    environment: Optional[Dict[str, str]] = None
    hyperparameters: Optional[Dict[str, Any]] = None
    tags: Optional[List[Tag]] = None

    # Created Artifacts
    _latest_training_job: Optional[resources.TrainingJob] = None

    # Metrics settings
    _enable_sage_maker_metrics_time_series: Optional[bool] = PrivateAttr(default=False)
    _metric_definitions: Optional[List[MetricDefinition]] = PrivateAttr(default=None)

    # Debugger settings
    _debug_hook_config: Optional[DebugHookConfig] = PrivateAttr(default=None)
    _debug_rule_configurations: Optional[List[DebugRuleConfiguration]] = PrivateAttr(default=None)
    _remote_debug_config: Optional[RemoteDebugConfig] = PrivateAttr(default=None)
    _profiler_config: Optional[ProfilerConfig] = PrivateAttr(default=None)
    _profiler_rule_configurations: Optional[List[ProfilerRuleConfiguration]] = PrivateAttr(
        default=None
    )
    _tensor_board_output_config: Optional[TensorBoardOutputConfig] = PrivateAttr(default=None)

    # Additional settings
    _retry_strategy: Optional[RetryStrategy] = PrivateAttr(default=None)
    _experiment_config: Optional[ExperimentConfig] = PrivateAttr(default=None)
    _infra_check_config: Optional[InfraCheckConfig] = PrivateAttr(default=None)
    _session_chaining_config: Optional[SessionChainingConfig] = PrivateAttr(default=None)
    _remote_debug_config: Optional[RemoteDebugConfig] = PrivateAttr(default=None)

    def _validate_training_image_and_algorithm_name(
        self, training_image: Optional[str], algorithm_name: Optional[str]
    ):
        """Validate that only one of 'training_image' or 'algorithm_name' is provided."""
        if not training_image and not algorithm_name:
            raise ValueError(
                "Atleast one of 'training_image' or 'algorithm_name' must be provided.",
            )
        if training_image and algorithm_name:
            raise ValueError(
                "Only one of 'training_image' or 'algorithm_name' must be provided.",
            )

    def _validate_distributed_runner(
        self,
        source_code: Optional[SourceCode],
        distributed_runner: Optional[DistributedRunner],
    ):
        """Validate the distribution configuration."""
        if distributed_runner and not source_code.entry_script:
            raise ValueError(
                "Must provide 'entry_script' if 'distribution' " + "is provided in 'source_code'.",
            )

    # TODO: Move to use pydantic model validators
    def _validate_source_code(self, source_code: Optional[SourceCode]):
        """Validate the source code configuration."""
        if source_code:
            if source_code.requirements or source_code.entry_script:
                source_dir = source_code.source_dir
                requirements = source_code.requirements
                entry_script = source_code.entry_script
                if not source_dir:
                    raise ValueError(
                        "If 'requirements' or 'entry_script' is provided in 'source_code', "
                        + "'source_dir' must also be provided.",
                    )
                if not _is_valid_path(source_dir, path_type="Directory"):
                    raise ValueError(
                        f"Invalid 'source_dir' path: {source_dir}. " + "Must be a valid directory.",
                    )
                if requirements:
                    if not _is_valid_path(
                        f"{source_dir}/{requirements}",
                        path_type="File",
                    ):
                        raise ValueError(
                            f"Invalid 'requirements': {requirements}. "
                            + "Must be a valid file within the 'source_dir'.",
                        )
                if entry_script:
                    if not _is_valid_path(
                        f"{source_dir}/{entry_script}",
                        path_type="File",
                    ):
                        raise ValueError(
                            f"Invalid 'entry_script': {entry_script}. "
                            + "Must be a valid file within the 'source_dir'.",
                        )

    def model_post_init(self, __context: Any):
        """Post init method to perform custom validation and set default values."""
        self._validate_training_image_and_algorithm_name(self.training_image, self.algorithm_name)
        self._validate_source_code(self.source_code)
        self._validate_distributed_runner(self.source_code, self.distributed_runner)

        if self.session is None:
            self.session = Session()
            logger.warning("Session not provided. Using default Session.")

        if self.role is None:
            self.role = get_execution_role()
            logger.warning(f"Role not provided. Using default role:\n{self.role}")

        if self.base_job_name is None:
            if self.algorithm_name:
                self.base_job_name = f"{self.algorithm_name}-job"
            elif self.training_image:
                self.base_job_name = f"{_get_repo_name_from_image(self.training_image)}-job"
            logger.warning(f"Base name not provided. Using default name:\n{self.base_job_name}")

        if self.compute is None:
            self.compute = Compute(
                instance_type=DEFAULT_INSTANCE_TYPE,
                instance_count=1,
                volume_size_in_gb=30,
            )
            logger.warning(f"Compute not provided. Using default:\n{self.compute}")

        if self.stopping_condition is None:
            self.stopping_condition = StoppingCondition(
                max_runtime_in_seconds=3600,
                max_pending_time_in_seconds=None,
                max_wait_time_in_seconds=None,
            )
            logger.warning(
                f"StoppingCondition not provided. Using default:\n{self.stopping_condition}"
            )

        if self.output_data_config is None:
            session = self.session
            base_job_name = self.base_job_name
            self.output_data_config = OutputDataConfig(
                s3_output_path=f"s3://{session.default_bucket()}/{base_job_name}",
                compression_type="GZIP",
                kms_key_id=None,
            )
            logger.warning(
                f"OutputDataConfig not provided. Using default:\n{self.output_data_config}"
            )

        # TODO: Autodetect which image to use if source_code is provided
        if self.training_image:
            logger.info(f"Training image URI: {self.training_image}")

    @validate_call
    def train(
        self,
        input_data_config: Optional[List[Union[Channel, InputData]]] = None,
        wait: Optional[bool] = True,
        logs: Optional[bool] = True,
    ):
        """Train a model using AWS SageMaker.

        Args:
            input_data_config (Optional[Union[List[Channel], Dict[str, DataSourceType]]]):
                The input data config for the training job.
                Takes a list of Channel objects or a dictionary of channel names to DataSourceType.
                DataSourceType can be an S3 URI string, local file path string,
                S3DataSource object, or FileSystemDataSource object.
            wait (Optional[bool]):
                Whether to wait for the training job to complete before returning.
                Defaults to True.
            logs (Optional[bool]):
                Whether to display the training container logs while training.
                Defaults to True.
        """
        if input_data_config:
            self.input_data_config = input_data_config

        input_data_config = []
        if self.input_data_config:
            input_data_config = self._get_input_data_config(self.input_data_config)

        string_hyper_parameters = {}
        if self.hyperparameters:
            for hyper_parameter, value in self.hyperparameters.items():
                string_hyper_parameters[hyper_parameter] = safe_serialize(value)

        container_entrypoint = None
        container_arguments = None
        if self.source_code:

            drivers_dir = TemporaryDirectory()
            shutil.copytree(SM_DRIVERS_LOCAL_PATH, drivers_dir.name, dirs_exist_ok=True)

            # If source code is provided, create a channel for the source code
            # The source code will be mounted at /opt/ml/input/data/sm_code in the container
            if self.source_code.source_dir:
                source_code_channel = self.create_input_data_channel(
                    SM_CODE, self.source_code.source_dir
                )
                input_data_config.append(source_code_channel)

            self._prepare_train_script(
                tmp_dir=drivers_dir,
                source_code=self.source_code,
                distributed_runner=self.distributed_runner,
            )

            if isinstance(self.distributed_runner, TorchrunSMP):
                mp_parameters = self.distributed_runner._to_mp_parameters_dict()
                string_hyper_parameters["mp_parameters"] = safe_serialize(mp_parameters)

            self._write_source_code_json(tmp_dir=drivers_dir, source_code=self.source_code)
            self._write_distributed_runner_json(
                tmp_dir=drivers_dir, distributed_runner=self.distributed_runner
            )

            # Create an input channel for drivers packaged by the sdk
            sm_drivers_channel = self.create_input_data_channel(SM_DRIVERS, drivers_dir.name)
            input_data_config.append(sm_drivers_channel)

            # If source_code is provided, we will always use
            # the default container entrypoint and arguments
            # to execute the sm_train.sh script.
            # Any commands generated from the source_code will be
            # executed from the sm_train.sh script.
            container_entrypoint = DEFAULT_CONTAINER_ENTRYPOINT
            container_arguments = DEFAULT_CONTAINER_ARGUMENTS

        algorithm_specification = AlgorithmSpecification(
            algorithm_name=self.algorithm_name,
            training_image=self.training_image,
            training_input_mode=self.training_input_mode,
            training_image_config=self.training_image_config,
            container_entrypoint=container_entrypoint,
            container_arguments=container_arguments,
            metric_definitions=self._metric_definitions,
            enable_sage_maker_metrics_time_series=self._enable_sage_maker_metrics_time_series,
        )

        resource_config = self.compute._to_resource_config()
        vpc_config = self.networking._to_vpc_config() if self.networking else None

        training_job = TrainingJob.create(
            training_job_name=_get_unique_name(self.base_job_name),
            algorithm_specification=algorithm_specification,
            hyper_parameters=string_hyper_parameters,
            input_data_config=input_data_config,
            resource_config=resource_config,
            vpc_config=vpc_config,
            # Public Instance Attributes
            session=self.session.boto_session,
            role_arn=self.role,
            tags=self.tags,
            stopping_condition=self.stopping_condition,
            output_data_config=self.output_data_config,
            checkpoint_config=self.checkpoint_config,
            environment=self.environment,
            enable_managed_spot_training=self.compute.enable_managed_spot_training,
            enable_inter_container_traffic_encryption=(
                self.networking.enable_inter_container_traffic_encryption
                if self.networking
                else None
            ),
            enable_network_isolation=(
                self.networking.enable_network_isolation if self.networking else None
            ),
            # Private Instance Attributes
            debug_hook_config=self._debug_hook_config,
            debug_rule_configurations=self._debug_rule_configurations,
            remote_debug_config=self._remote_debug_config,
            profiler_config=self._profiler_config,
            profiler_rule_configurations=self._profiler_rule_configurations,
            tensor_board_output_config=self._tensor_board_output_config,
            retry_strategy=self._retry_strategy,
            experiment_config=self._experiment_config,
            infra_check_config=self._infra_check_config,
            session_chaining_config=self._session_chaining_config,
        )
        self._latest_training_job = training_job
        if wait:
            training_job.wait(logs=logs)

    def create_input_data_channel(self, channel_name: str, data_source: DataSourceType) -> Channel:
        """Create an input data channel for the training job.

        Args:
            channel_name (str): The name of the input data channel.
            data_source (DataSourceType): The data source for the input data channel.
                DataSourceType can be an S3 URI string, local file path string,
                S3DataSource object, or FileSystemDataSource object.
        """
        channel = None
        if isinstance(data_source, str):
            if _is_valid_s3_uri(data_source):
                channel = Channel(
                    channel_name=channel_name,
                    data_source=DataSource(
                        s3_data_source=S3DataSource(
                            s3_data_type="S3Prefix",
                            s3_uri=data_source,
                            s3_data_distribution_type="FullyReplicated",
                        ),
                    ),
                    input_mode="File",
                )
            elif _is_valid_path(data_source):
                s3_uri = self.session.upload_data(
                    path=data_source,
                    bucket=self.session.default_bucket(),
                    key_prefix=f"{self.base_job_name}/input/{channel_name}",
                )
                channel = Channel(
                    channel_name=channel_name,
                    data_source=DataSource(
                        s3_data_source=S3DataSource(
                            s3_data_type="S3Prefix",
                            s3_uri=s3_uri,
                            s3_data_distribution_type="FullyReplicated",
                        ),
                    ),
                    input_mode="File",
                )
            else:
                raise ValueError(f"Not a valid S3 URI or local file path: {data_source}.")
        elif isinstance(data_source, S3DataSource):
            channel = Channel(
                channel_name=channel_name, data_source=DataSource(s3_data_source=data_source)
            )
        elif isinstance(data_source, FileSystemDataSource):
            channel = Channel(
                channel_name=channel_name,
                data_source=DataSource(file_system_data_source=data_source),
            )
        return channel

    def _get_input_data_config(
        self, input_data_channels: Optional[List[Union[Channel, InputData]]]
    ) -> List[Channel]:
        """Get the input data configuration for the training job.

        Args:
            input_data_channels (Optional[List[Union[Channel, InputData]]]):
                The input data config for the training job.
                Takes a list of Channel or InputData objects. An InputDataSource can be an S3 URI
                string, local file path string, S3DataSource object, or FileSystemDataSource object.
        """
        if input_data_channels is None:
            return []

        channels = []
        for input_data in input_data_channels:
            if isinstance(input_data, Channel):
                channels.append(input)
            elif isinstance(input_data, InputData):
                channel = self.create_input_data_channel(
                    input_data.channel_name, input_data.data_source
                )
                channels.append(channel)
            else:
                raise ValueError(
                    f"Invalid input data channel: {input_data}. "
                    + "Must be a Channel or InputDataSource."
                )
        return channels

    def _write_source_code_json(self, tmp_dir: TemporaryDirectory, source_code: SourceCode):
        """Write the source code configuration to a JSON file."""
        file_path = os.path.join(tmp_dir.name, SOURCE_CODE_JSON)
        with open(file_path, "w") as f:
            dump = source_code.model_dump(exclude_none=True) if source_code else {}
            f.write(json.dumps(dump))

    def _write_distributed_runner_json(
        self,
        tmp_dir: TemporaryDirectory,
        distributed_runner: Optional[DistributedRunner] = None,
    ):
        """Write the distributed runner configuration to a JSON file."""
        file_path = os.path.join(tmp_dir.name, DISTRIBUTED_RUNNER_JSON)
        with open(file_path, "w") as f:
            dump = distributed_runner.model_dump(exclude_none=True) if distributed_runner else {}
            f.write(json.dumps(dump))

    def _prepare_train_script(
        self,
        tmp_dir: TemporaryDirectory,
        source_code: SourceCode,
        distributed_runner: Optional[DistributedRunner] = None,
    ):
        """Prepare the training script to be executed in the training job container.

        Args:
            source_code (SourceCodeConfig): The source code configuration.
        """

        base_command = ""
        if source_code.command:
            if source_code.entry_script:
                logger.warning(
                    "Both 'command' and 'entry_script' are provided in the SourceCodeConfig. "
                    + "Defaulting to 'command'."
                )
            base_command = source_code.command.split()
            base_command = " ".join(base_command)

        install_requirements = ""
        if source_code.requirements:
            install_requirements = "echo 'Installing requirements'\n"
            install_requirements = f"$SM_PIP_CMD install -r {source_code.requirements}"

        working_dir = ""
        if source_code.source_dir:
            working_dir = f"cd {SM_CODE_CONTAINER_PATH}"

        if base_command:
            execute_driver = EXECUTE_BASE_COMMANDS.format(base_command=base_command)
        elif distributed_runner:
            distribution_type = distributed_runner._type
            if distribution_type == "mpi":
                execute_driver = EXECUTE_MPI_DRIVER
            elif distribution_type == "torchrun":
                execute_driver = EXEUCTE_TORCHRUN_DRIVER
            else:
                raise ValueError(f"Unsupported distribution type: {distribution_type}.")
        elif source_code.entry_script and not source_code.command and not distributed_runner:
            if not source_code.entry_script.endswith((".py", ".sh")):
                raise ValueError(
                    f"Unsupported entry script: {source_code.entry_script}."
                    + "Only .py and .sh scripts are supported."
                )
            execute_driver = EXECUTE_BASIC_SCRIPT_DRIVER

        train_script = TRAIN_SCRIPT_TEMPLATE.format(
            working_dir=working_dir,
            install_requirements=install_requirements,
            execute_driver=execute_driver,
        )

        with open(os.path.join(tmp_dir.name, TRAIN_SCRIPT), "w") as f:
            f.write(train_script)

    def with_metric_settings(
        self,
        enable_sage_maker_metrics_time_series: bool = True,
        metric_definitions: Optional[List[MetricDefinition]] = None,
    ) -> "ModelTrainer":
        """Set the metrics configuration for the training job.

        Example:
        ```python
        model_trainer = ModelTrainer(...).with_metric_settings(
            enable_sage_maker_metrics_time_series=True,
            metric_definitions=[
                MetricDefinition(
                    name="loss",
                    regex="Loss: (.*?),",
                ),
                MetricDefinition(
                    name="accuracy",
                    regex="Accuracy: (.*?),",
                ),
            ]
        )
        ```

        Args:
            enable_sage_maker_metrics_time_series (Optional[bool]):
                Whether to enable SageMaker metrics time series. Defaults to True.
            metric_definitions (Optional[List[MetricDefinition]]):
                A list of metric definition objects. Each object specifies
                the metric name and regular expressions used to parse algorithm logs.
                SageMaker publishes each metric to Amazon CloudWatch.
        """
        self._enable_sage_maker_metrics_time_series = enable_sage_maker_metrics_time_series
        self._metric_definitions = metric_definitions
        return self

    def with_debugger_settings(
        self,
        debug_hook_config: Optional[DebugHookConfig] = None,
        debug_rule_configurations: Optional[List[DebugRuleConfiguration]] = None,
        profiler_config: Optional[ProfilerConfig] = None,
        profiler_rule_configurations: Optional[List[ProfilerRuleConfiguration]] = None,
        tensor_board_output_config: Optional[TensorBoardOutputConfig] = None,
    ) -> "ModelTrainer":
        """Set the configuration for settings related to Amazon SageMaker Debugger.

        Example:
        ```python
        model_trainer = ModelTrainer(...).with_debugger_settings(
            debug_hook_config=DebugHookConfig(
                s3_output_path="s3://bucket/path",
                collection_configurations=[
                    CollectionConfiguration(
                        collection_name="some_collection",
                        collection_parameters={
                            "include_regex": ".*",
                        }
                    )
                ]
            )
        )
        ```

        Args:
            debug_hook_config (Optional[DebugHookConfig]):
                Configuration information for the Amazon SageMaker Debugger hook parameters,
                metric and tensor collections, and storage paths.
                To learn more see: https://docs.aws.amazon.com/sagemaker/latest/dg/debugger-createtrainingjob-api.html
            debug_rule_configurations (Optional[List[DebugRuleConfiguration]]):
                Configuration information for Amazon SageMaker Debugger rules for debugging
                output ensors.
            profiler_config (ProfilerConfig):
                Configuration information for Amazon SageMaker Debugger system monitoring,
                framework profiling, and storage paths.
            profiler_rule_configurations (List[ProfilerRuleConfiguration]):
                Configuration information for Amazon SageMaker Debugger rules for profiling
                system and framework metrics.
            tensor_board_output_config (Optional[TensorBoardOutputConfig]):
                Configuration of storage locations for the Amazon SageMaker Debugger TensorBoard
                output data.
        """
        self._debug_hook_config = debug_hook_config
        self._debug_rule_configurations = debug_rule_configurations
        self._profiler_config = profiler_config
        self._profiler_rule_configurations = profiler_rule_configurations
        self._tensor_board_output_config = tensor_board_output_config
        return self

    def with_additional_settings(
        self,
        retry_strategy: Optional[RetryStrategy] = None,
        experiment_config: Optional[ExperimentConfig] = None,
        infra_check_config: Optional[InfraCheckConfig] = None,
        session_chaining_config: Optional[SessionChainingConfig] = None,
        remote_debug_config: Optional[RemoteDebugConfig] = None,
    ) -> "ModelTrainer":
        """Set any additional settings for the training job.

        Example:
        ```python
        model_trainer = ModelTrainer(...).with_additional_settings(
            experiment_config=ExperimentConfig(
                experiment_name="my-experiment",
                trial_name="my-trial",
            )
        )
        ```

        Args:
            retry_strategy (Optional[RetryStrategy]):
                The number of times to retry the job when the job fails due to an
                `InternalServerError`.
            experiment_config (Optional[ExperimentConfig]):
                Configuration information for the Amazon SageMaker Experiment.
                Associates a SageMaker job as a trial component with an experiment and trial
            infra_check_config (Optional[InfraCheckConfig]):
                Contains information about the infrastructure health check configuration for the
                training job.
            session_chaining_config (Optional[SessionChainingConfig]):
                Contains information about attribute-based access control (ABAC) for the training
                job.
            remote_debug_config (Optional[RemoteDebugConfig]):
                Configuration for remote debugging through AWS Systems Manager. To learn more see:
                https://docs.aws.amazon.com/sagemaker/latest/dg/train-remote-debugging.html
        """
        self._retry_strategy = retry_strategy
        self._experiment_config = experiment_config
        self._infra_check_config = infra_check_config
        self._session_chaining_config = session_chaining_config
        self._remote_debug_config = remote_debug_config
        return self
