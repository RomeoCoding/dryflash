import pytest

from dryflash.sensors.models import SensorSpecError, make_model


def writes_by_bank(writes):
    return {(bank, off): data for bank, off, data in writes}


class TestAdxl345:
    def model(self, **kw):
        spec = {"model": "adxl345", "name": "accel", "waveform": {"x": 1.0, "y": -0.5, "z": 0.0}}
        spec.update(kw)
        return make_model(spec)

    def test_defaults_and_device_props(self):
        m = self.model()
        assert (m.address, m.bus, m.rate_hz) == (0x53, 0, 400)
        p = m.device_props()
        assert p["bank-reg"] == "0x31" and p["bank-width"] == "1" and p["bank-mask"] == "0x0b"
        assert p["bank-first"] == "0x32" and p["bank-last"] == "0x37"
        assert "0x30:0x80" in p["read-set"]

    def test_initial_registers(self):
        w = writes_by_bank(self.model().initial_writes())
        regs = w[(-1, 0)]
        assert regs[0x00] == 0xE5          # DEVID
        assert regs[0x2C] == 0x0A          # BW_RATE: 100 Hz
        assert regs[0x30] & 0x80           # DATA_READY

    def test_full_res_2g_is_256_lsb_per_g_little_endian(self):
        w = writes_by_bank(self.model().encode({"x": 1.0, "y": -0.5, "z": 0.0}))
        assert w[(0x08, 0x32)] == bytes([0x00, 0x01, 0x80, 0xFF, 0x00, 0x00])  # 256, -128, 0

    def test_ranges_and_clipping(self):
        m = self.model()
        w = writes_by_bank(m.encode({"x": 3.0, "y": 0.0, "z": 0.0}))
        assert int.from_bytes(w[(0x00, 0x32)][:2], "little", signed=True) == 511    # 10-bit ±2g clips
        assert int.from_bytes(w[(0x01, 0x32)][:2], "little", signed=True) == 384    # ±4g: 128/g
        assert int.from_bytes(w[(0x03, 0x32)][:2], "little", signed=True) == 96     # ±16g: 32/g
        assert int.from_bytes(w[(0x0B, 0x32)][:2], "little", signed=True) == 768    # full-res ±16g: 256/g
        assert sorted({b for b, _ in w}) == [0, 1, 2, 3, 8, 9, 10, 11]

    def test_guest_config_is_described(self):
        m = self.model()
        m.on_guest_write(0x31, bytes([0x0B]))
        m.on_guest_write(0x2C, bytes([0x0D]))
        d = m.describe()
        assert d["guest_config"]["range_g"] == 16 and d["guest_config"]["full_resolution"] is True
        assert d["guest_config"]["output_data_rate_hz"] == 800


class TestAds1115:
    def model(self, **kw):
        spec = {"model": "ads1115", "name": "adc",
                "waveform": {"ain0": 1.0, "ain1": 0.25, "ain2": -0.1, "ain3": 3.3}}
        spec.update(kw)
        return make_model(spec)

    def test_defaults_avoid_the_hardwired_tmp105(self):
        m = self.model()
        assert m.address == 0x49 and m.rate_hz == 250
        p = m.device_props()
        assert p["stride"] == "2" and p["bank-width"] == "2" and p["bank-mask"] == "0x7e00"
        assert p["bank-shift"] == "9" and p["read-set"] == "2:0x80"

    def test_initial_config_register(self):
        w = writes_by_bank(self.model().initial_writes())
        assert w[(-1, 2)] == bytes([0x85, 0x83, 0x80, 0x00, 0x7F, 0xFF])

    def test_conversion_codes_per_mux_and_pga(self):
        w = writes_by_bank(self.model().encode({"ain0": 1.0, "ain1": 0.25, "ain2": -0.1, "ain3": 3.3}))
        def code(mux, pga):
            return int.from_bytes(w[(mux << 3 | pga, 0)], "big", signed=True)
        assert code(4, 2) == 16000                  # AIN0 1.0 V at ±2.048 V
        assert code(4, 1) == 8000                   # ±4.096 V
        assert code(0, 2) == 12000                  # AIN0-AIN1 = 0.75 V
        assert code(7, 2) == 32767                  # AIN3 3.3 V clips at ±2.048
        assert code(7, 0) == round(3.3 / 6.144 * 32768)
        assert code(3, 5) == -32768                 # AIN2-AIN3 = -3.4 V clips negative
        assert len({b for b, _ in w}) == 64

    def test_address_override_and_bad_address(self):
        assert self.model(address=0x4A).address == 0x4A
        with pytest.raises(SensorSpecError, match="0x48"):
            self.model(address=0x48)


class TestMpu6050:
    """Vectors from RM-MPU-6000A-00 rev 4.0 (section numbers in the comments)."""

    def model(self, **kw):
        spec = {"model": "mpu6050", "name": "imu"}
        spec.update(kw)
        return make_model(spec)

    @staticmethod
    def words(data):
        return [int.from_bytes(data[i:i + 2], "big", signed=True) for i in range(0, len(data), 2)]

    def test_defaults_and_device_props(self):
        m = self.model()
        assert (m.address, m.bus, m.rate_hz) == (0x68, 0, 1000)
        p = m.device_props()
        # bank = SLEEP (PWR_MGMT_1 bit 6) | AFS_SEL << 1 | FS_SEL << 3, over ACCEL_XOUT_H..GYRO_ZOUT_L
        assert p["bank-fields"] == "0x6b:0x40,0x1c:0x18,0x1b:0x18"
        assert (p["bank-first"], p["bank-last"]) == ("0x3b", "0x48")
        assert p["read-set"] == "0x3a:0x01"                  # INT_STATUS DATA_RDY_INT (4.17)
        assert "0x6b:0x80" in p["write-clear"]               # DEVICE_RESET self-clears (4.30)
        assert "0x75" in p["read-only"]

    def test_power_on_registers(self):
        regs = writes_by_bank(self.model().initial_writes())[(-1, 0)]
        assert regs[0x6B] == 0x40                            # PWR_MGMT_1 resets to sleep (section 3)
        assert regs[0x75] == 0x68                            # WHO_AM_I (4.34)
        assert regs[0x1B] == regs[0x1C] == 0x00

    def test_address_0x69_allowed_but_whoami_stays_0x68(self):
        m = self.model(address=0x69)
        assert m.address == 0x69
        assert writes_by_bank(m.initial_writes())[(-1, 0)][0x75] == 0x68

    @pytest.mark.parametrize("address", [0x53, 0x6A])
    def test_other_addresses_rejected(self, address):
        with pytest.raises(SensorSpecError, match="0x68 or 0x69"):
            self.model(address=address)

    def test_only_awake_banks_are_written(self):
        w = self.model().encode({c: 0.0 for c in ("x", "y", "z", "gx", "gy", "gz", "temp_c")})
        banks = sorted({b for b, _, _ in w})
        assert banks == [afs << 1 | fs << 3 for fs in range(4) for afs in range(4)]
        assert all(b & 1 == 0 for b in banks)                # sleep banks stay zero
        assert {off for _, off, _ in w} == {0x3B} and {len(d) for _, _, d in w} == {14}

    @pytest.mark.parametrize("afs, lsb_per_g", [(0, 16384), (1, 8192), (2, 4096), (3, 2048)])
    def test_accel_scaling_per_afs_sel(self, afs, lsb_per_g):              # 4.18
        w = writes_by_bank(self.model().encode({"x": 0.5, "y": -1.0, "z": 0.25, "gx": 0, "gy": 0, "gz": 0,
                                                 "temp_c": 36.53}))
        ax, ay, az, t, *_ = self.words(w[(afs << 1, 0x3B)])
        assert (ax, ay, az) == (lsb_per_g // 2, -lsb_per_g, lsb_per_g // 4)
        assert t == 0                                        # 36.53 degC is raw 0 (4.19)

    @pytest.mark.parametrize("fs, lsb_per_dps", [(0, 131.0), (1, 65.5), (2, 32.8), (3, 16.4)])
    def test_gyro_scaling_per_fs_sel(self, fs, lsb_per_dps):              # 4.20
        w = writes_by_bank(self.model().encode({"x": 0, "y": 0, "z": 0, "gx": 100.0, "gy": -10.0, "gz": 0.0,
                                                 "temp_c": 25.0}))
        *_, gx, gy, gz = self.words(w[(fs << 3, 0x3B)])
        assert (gx, gy, gz) == (round(100 * lsb_per_dps), round(-10 * lsb_per_dps), 0)

    def test_temperature_and_clipping(self):
        w = writes_by_bank(self.model().encode({"x": 3.0, "y": -3.0, "z": 0, "gx": 300.0, "gy": 0, "gz": 0,
                                                 "temp_c": 25.0}))
        ax, ay, _, t, gx, *_ = self.words(w[(0, 0x3B)])
        assert (ax, ay) == (32767, -32768)                   # +-2 g full scale clips
        assert gx == 32767                                   # 300 deg/s beyond +-250
        assert t == round((25.0 - 36.53) * 340)              # T = raw/340 + 36.53 (4.19)

    def test_guest_config_is_described(self):
        m = self.model()
        assert m.describe()["guest_config"]["sleeping"] is True
        m.on_guest_write(0x19, bytes([4, 0x03, 0x10, 0x08]))  # SMPLRT_DIV 4, DLPF 3, FS_SEL 2, AFS_SEL 1
        m.on_guest_write(0x6B, bytes([0x01]))
        g = m.describe()["guest_config"]
        assert g == {"sleeping": False, "accel_range_g": 4, "gyro_range_dps": 1000,
                     "sample_rate_hz": 200.0, "dlpf_cfg": 3, "clock_source": 1}


class TestGeneric:
    def test_channels_registers_and_props(self):
        m = make_model({
            "model": "generic", "name": "temp", "address": 0x40,
            "registers": {"0x00": "0xA5", "0x10": [1, 2]},
            "read_only": "0x00", "read_set": "0x01:0x01",
            "channels": {"t": {"offset": "0x02", "format": "int16_be", "scale": 128, "bias": 0}},
            "waveform": {"t": 21.5}})
        assert m.device_props() == {"stride": "1", "read-only": "0x00", "read-set": "0x01:0x01"}
        init = writes_by_bank(m.initial_writes())
        assert init[(-1, 0)][0] == 0xA5 and init[(-1, 0)][0x10:0x12] == bytes([1, 2])
        w = m.encode({"t": 21.5})
        assert w == [(-1, 2, (2752).to_bytes(2, "big"))]

    def test_unsigned_clipping(self):
        m = make_model({"model": "generic", "name": "g", "address": 0x41,
                        "channels": {"v": {"offset": 0, "format": "uint8"}}, "waveform": {"v": 300}})
        assert m.encode({"v": 300}) == [(-1, 0, bytes([255]))]


@pytest.mark.parametrize("spec, msg", [
    ({"model": "bmp999", "name": "x"}, "unknown sensor model"),
    ({"model": "adxl345"}, "name"),
    ({"model": "adxl345", "name": "a", "waveform": {"w": 1}}, "unknown channel"),
    ({"model": "adxl345", "name": "a", "bus": 2}, "bus"),
    ({"model": "generic", "name": "g", "address": 0x40, "channels": {"v": {"offset": 0, "format": "f32"}}},
     "format"),
])
def test_spec_errors(spec, msg):
    with pytest.raises(SensorSpecError, match=msg):
        make_model(spec)


def test_missing_channels_default_to_zero_and_timeline_switches():
    m = make_model({"model": "adxl345", "name": "a", "waveform": {"z": 1.0}})
    assert m.values_at(0) == {"x": 0.0, "y": 0.0, "z": 1.0}
    m.schedule(1_000_000_000, {"x": 0.5})
    assert m.values_at(999_999_999)["x"] == 0.0
    assert m.values_at(1_000_000_000) == {"x": 0.5, "y": 0.0, "z": 1.0}
