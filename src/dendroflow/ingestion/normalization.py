import pandas as pd

from dendroflow.tabular import TabularBatch

from .models import (
    Deployment,
    NormalizedObservation,
    SourceFile,
    SourceInterface,
)

def normalize_batch(
    batch: TabularBatch,
    source_file: SourceFile,
    interfaces: tuple[SourceInterface, ...],
    deployments: dict[int, Deployment],
) -> tuple[NormalizedObservation, ...]:
    """Convert one tabular batch into normalized RAW observations."""

    dataframe = batch.dataframe
    observations: list[NormalizedObservation] = []

    for interface in interfaces:
        if interface.values_column not in dataframe.columns:
            raise ValueError(
                f"Missing values column: {interface.values_column}"
            )

        if interface.timestamp_column not in dataframe.columns:
            raise ValueError(
                f"Missing timestamp column: {interface.timestamp_column}"
            )

        deployment = deployments.get(interface.deployment_id)

        if deployment is None:
            raise ValueError(
                f"Missing deployment: {interface.deployment_id}"
            )

        timestamps = pd.to_datetime(
            dataframe[interface.timestamp_column],
            format=source_file.timestamp_format,
            errors="raise",
        )

        timestamps = timestamps.dt.tz_localize(
            source_file.timestamp_timezone,
        )

        values = dataframe[interface.values_column]

        for timestamp, value, source_row_number in zip(
            timestamps,
            values,
            batch.source_line_numbers,
        ):
            timestamp_python = timestamp.to_pydatetime()

            if timestamp_python < deployment.valid_from:
                raise ValueError(
                    "Observation timestamp precedes deployment "
                    f"{deployment.deployment_id}: "
                    f"source line {source_row_number}"
                )

            if (
                deployment.valid_to is not None
                and timestamp_python >= deployment.valid_to
            ):
                raise ValueError(
                    "Observation timestamp exceeds deployment "
                    f"{deployment.deployment_id}: "
                    f"source line {source_row_number}"
                )

            if pd.isna(value):
                normalized_value = float("nan")
            else:
                normalized_value = float(value)

            observations.append(
                NormalizedObservation(
                    location_id=deployment.location_id,
                    variable_id=deployment.variable_id,
                    timestamp=timestamp_python,
                    value=normalized_value,
                    interface_id=interface.interface_id,
                    source_row_number=source_row_number,
                )
            )

    return tuple(observations)
