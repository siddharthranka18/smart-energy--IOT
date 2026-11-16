"""PostgreSQL table for historical room telemetry."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Double, Index, Integer, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ControlAction(Base):
    __tablename__ = "control_actions"

    command_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    target: Mapped[str] = mapped_column(String(5), server_default=text("'light'"))
    before_w: Mapped[float] = mapped_column(Double)
    before_sequence: Mapped[int] = mapped_column(BigInteger)
    before_uptime_ms: Mapped[int] = mapped_column(BigInteger)
    ack_uptime_ms: Mapped[int | None] = mapped_column(BigInteger)
    after_w: Mapped[float | None] = mapped_column(Double)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(String(100))


class TelemetrySample(Base):
    """One validated telemetry message.

    energy_wh and estimated_cost_inr are the device counters. energy_delta_wh
    and cost_delta_inr are the amounts added to the server totals. Current is
    the simulated sensor value published by the firmware.
    """

    __tablename__ = "telemetry_samples"
    __table_args__ = (
        Index("ix_telemetry_device_received", "device_id", "received_at"),
        Index("ix_telemetry_device_sequence", "device_id", "sequence", "uptime_ms"),
        {
            "comment": (
                "Historical telemetry from the ESP32. "
                "Current and power are simulated, not read from a physical meter."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mqtt_topic: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    firmware_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uptime_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    occupied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ldr_raw: Mapped[int] = mapped_column(Integer, nullable=False)
    is_dark: Mapped[bool] = mapped_column(Boolean, nullable=False)
    temperature_c: Mapped[float | None] = mapped_column(Double, nullable=True)
    humidity_percent: Mapped[float | None] = mapped_column(Double, nullable=True)
    dht_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    light_on: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fan_on: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ac_on: Mapped[bool] = mapped_column(Boolean, nullable=False)
    control_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)

    current_sensor_raw: Mapped[int] = mapped_column(Integer, nullable=False)
    power_sensor_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    voltage_v: Mapped[float] = mapped_column(Double, nullable=False)
    sensor_current_a: Mapped[float] = mapped_column(Double, nullable=False)
    current_a: Mapped[float] = mapped_column(Double, nullable=False)
    load_model_power_w: Mapped[float] = mapped_column(Double, nullable=False)
    power_w: Mapped[float] = mapped_column(Double, nullable=False)
    energy_wh: Mapped[float] = mapped_column(Double, nullable=False)
    energy_kwh: Mapped[float] = mapped_column(Double, nullable=False)
    estimated_cost_inr: Mapped[float] = mapped_column(Double, nullable=False)
    high_power_alert: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unoccupied_power_alert: Mapped[bool] = mapped_column(Boolean, nullable=False)

    energy_delta_wh: Mapped[float] = mapped_column(Double, nullable=False)
    cost_delta_inr: Mapped[float] = mapped_column(Double, nullable=False)
    device_counter_reset: Mapped[bool] = mapped_column(Boolean, nullable=False)
