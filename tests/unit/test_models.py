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
