"""MAX31855 / MAX6675 frames (datasheet tables) and the SSD1306 stream decoder."""

import pytest

from dryflash.sensors.display import Ssd1306State, read_text, text_art, write_png
from dryflash.sensors.font5x7 import FONT5X7
from dryflash.sensors.models import SensorSpecError, make_model


def tc(**kw):
    spec = {"model": "max31855", "name": "tc", "bus": "spi3", "cs": 0}
    spec.update(kw)
    return make_model(spec)


class TestMax31855:
    # MAX31855 19-5793 Rev 2, Table 4 (D[31:18]) and Table 5 (D[15:4])
    @pytest.mark.parametrize("t, bits", [(1600.0, 0b01100100000000), (1000.0, 0b00111110100000),
                                         (100.75, 0b00000110010011), (25.0, 0b00000001100100),
                                         (0.0, 0), (-0.25, 0b11111111111111), (-1.0, 0b11111111111100),
                                         (-250.0, 0b11110000011000)])
    def test_thermocouple_table_4(self, t, bits):
        word = tc().frame({"tc_c": t, "cj_c": 0.0, "fault": 0})
        assert word >> 18 == bits and word & 0x3FFFF == 0

    @pytest.mark.parametrize("t, bits", [(127.0, 0b011111110000), (100.5625, 0b011001001001),
                                         (25.0, 0b000110010000), (-0.0625, 0b111111111111),
                                         (-1.0, 0b111111110000), (-20.0, 0b111011000000),
                                         (-55.0, 0b110010010000)])
    def test_reference_junction_table_5(self, t, bits):
        word = tc().frame({"tc_c": 0.0, "cj_c": t, "fault": 0})
        assert (word >> 4) & 0xFFF == bits and word >> 16 == 0

    @pytest.mark.parametrize("fault, low_bits", [("open", 0b001), ("short_gnd", 0b010), ("short_vcc", 0b100)])
    def test_faults_set_d16_and_their_bit(self, fault, low_bits):
        m = tc(waveform={"tc_c": 25.0, "cj_c": 21.0, "fault": fault})
        word = int.from_bytes(m.encode(m.values_at(0))[0][2], "big")
        assert word >> 16 & 1 == 1 and word & 0x7 == low_bits and word >> 17 & 1 == 0 and word >> 3 & 1 == 0

    def test_open_input_reads_sign_0_and_all_ones(self):
        word = tc().frame({"tc_c": 25.0, "cj_c": 21.0, "fault": 1})
        assert word >> 18 == 0x1FFF

    def test_fault_step_from_none_to_open(self):
        m = tc(waveform={"tc_c": 80.0, "fault": {"type": "step", "steps": [[0, "none"], [5, "open"]]}})
        before = int.from_bytes(m.encode(m.values_at(4_999_000_000))[0][2], "big")
        after = int.from_bytes(m.encode(m.values_at(5_000_000_000))[0][2], "big")
        assert before & 0x10007 == 0 and after & 0x10007 == 0x10001

    def test_spec_and_device(self):
        m = tc(cs_gpio=5)
        assert (m.bus, m.cs, m.cs_gpio, m.rate_hz) == ("spi3", 0, 5, 10.0)
        assert m.device_props() == {"mode": "frame"}
        assert m.describe()["faults"] == ["none", "open", "short_gnd", "short_vcc"]

    @pytest.mark.parametrize("kw, msg", [({"bus": 0}, "spi2, spi3"), ({"cs": 3}, "cs must be 0-2"),
                                         ({"cs_gpio": 24}, "not an ESP32 GPIO"), ({"address": 5}, "SPI device"),
                                         ({"waveform": {"fault": "melted"}}, "unknown fault")])
    def test_errors_name_the_field(self, kw, msg):
        with pytest.raises(SensorSpecError, match=msg):
            tc(**kw)

    def test_i2c_models_reject_spi_keys(self):
        with pytest.raises(SensorSpecError, match="cs applies to SPI"):
            make_model({"model": "adxl345", "name": "a", "cs": 0})


class TestMax6675:
    def model(self, **kw):
        return make_model({"model": "max6675", "name": "tc", "bus": "spi2", **kw})

    @pytest.mark.parametrize("t, raw", [(0.0, 0), (1023.75, 4095), (25.0, 100), (-5.0, 0), (2000.0, 4095)])
    def test_temperature_bits(self, t, raw):
        assert self.model().frame({"tc_c": t, "fault": 0}) == raw << 3

    def test_open_is_d2_and_other_faults_are_rejected(self):
        assert self.model().frame({"tc_c": 25.0, "fault": 1}) & 0x7 == 0x4
        with pytest.raises(SensorSpecError, match="only detects an open input"):
            self.model(waveform={"fault": "short_gnd"})


def _cmd(*b):
    return bytes([0x00, *b])


def _data(*b):
    return bytes([0x40, *b])


class TestSsd1306:
    def init(self, d=None):
        d = d or Ssd1306State()
        # The usual Adafruit 128x64 initialisation (one command transfer, Co=0, D/C#=0)
        d.feed_transfer(_cmd(0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00,
                             0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF))
        return d

    def test_init_sequence_parses_arguments(self):
        d = self.init()
        assert d.describe() | {} == {"on": True, "inverted": False, "entire_display_on": False, "contrast": 0xCF,
                                     "width": 128, "height": 64, "addressing_mode": "horizontal",
                                     "charge_pump": True, "data_bytes": 0, "commands": 16}

    def test_horizontal_mode_wraps_into_the_next_page(self):
        d = self.init()
        d.feed_transfer(_cmd(0x21, 126, 127, 0x22, 2, 3))
        d.feed_transfer(_data(1, 2, 3, 4, 5))
        # 1, 2 on page 2; 3, 4 on page 3; the 5th byte wraps to (126, page 2) and overwrites the 1
        assert d.ram[2 * 128 + 126:2 * 128 + 128] == bytes([5, 2]) and d.ram[3 * 128 + 126:3 * 128 + 128] == bytes([3, 4])
        assert (d.col, d.page) == (127, 2)

    def test_page_mode_wraps_the_column_only(self):
        d = Ssd1306State()  # page mode at reset
        d.feed_transfer(_cmd(0xB5, 0x0E, 0x17))  # page 5, column 0x7E
        d.feed_transfer(_data(9, 8, 7))
        # the third byte wraps to the column start (0x7E) on the same page
        assert d.ram[5 * 128 + 126:5 * 128 + 128] == bytes([7, 8]) and d.ram[6 * 128 + 126] == 0
        assert (d.page, d.col) == (5, 127)

    def test_vertical_mode(self):
        d = Ssd1306State()
        d.feed_transfer(_cmd(0x20, 0x01, 0x21, 0, 127, 0x22, 0, 1))
        d.feed_transfer(_data(1, 2, 3))
        assert d.ram[0] == 1 and d.ram[128] == 2 and d.ram[1] == 3

    def test_co_bit_alternates_control_and_data(self):
        d = Ssd1306State()
        d.feed_transfer(bytes([0x80, 0xAF, 0x80, 0x81, 0x80, 0x10, 0xC0, 0x55]))
        assert d.on and d.contrast == 0x10 and d.ram[0] == 0x55

    def test_arguments_may_span_transfers(self):
        d = Ssd1306State()
        d.feed_transfer(_cmd(0x81))
        d.feed_transfer(_cmd(0x22))
        assert d.contrast == 0x22

    def draw(self, d, text, col, page, scale=1):
        """Text the way Adafruit_GFX draws it with size `scale`, starting on a page boundary."""
        img_cols = []
        for ch in text:
            img_cols += list(FONT5X7[ch]) + [0]
        for i, colbits in enumerate(img_cols):
            for k in range(8):
                if colbits >> k & 1:
                    for dx in range(scale):
                        for dy in range(scale):
                            x, y = col + i * scale + dx, page * 8 + k * scale + dy
                            d.ram[(y // 8) * 128 + x] |= 1 << (y % 8)

    @pytest.mark.parametrize("scale", [1, 2, 3])
    def test_read_text_finds_a_six_digit_code(self, scale):
        d = self.init()
        self.draw(d, "482913", 4, 1, scale)
        self.draw(d, "PAIR", 70, 6)
        lines = read_text(d.image())
        assert "482913" in lines and "PAIR" in lines

    def test_inverse_and_off_are_reported_and_art_is_cropped(self, tmp_path):
        d = self.init()
        self.draw(d, "7", 0, 0)
        art = text_art(d.image())
        assert art["box"] == {"x": 0, "y": 0, "width": 5, "height": 7} and len(art["art"].splitlines()) == 4
        d.feed_transfer(_cmd(0xA7, 0xAE))
        assert d.describe()["inverted"] and not d.describe()["on"]
        write_png(d.image(), tmp_path / "x.png")
        assert (tmp_path / "x.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_remap_off_mirrors_the_image(self):
        d = Ssd1306State()  # A0/C0 at reset
        d.ram[0] = 0x01      # column 0, row 0
        img = d.image()
        assert img[63][127] == 1 and img[0][0] == 0

    def test_model_is_a_stream_device(self):
        m = make_model({"model": "ssd1306", "name": "oled"})
        assert (m.address, m.device_props(), m.channels) == (0x3C, {"stream": "on"}, ())
        m.on_stream(5, _cmd(0xAF))
        assert m.describe()["guest_config"]["on"] is True
        with pytest.raises(SensorSpecError, match="0x3c or 0x3d"):
            make_model({"model": "ssd1306", "name": "oled", "address": 0x3E})
