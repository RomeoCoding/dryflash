"""Apply the throwaway M5 step-0 instrumentation to a QEMU tree at /dev-src/qemu.

Expects pristine esp-develop-9.2.2-20260417 + qemu-patches/0001-0006, with this directory
mounted at /spike. Not part of the patch series. `--fixes` also applies the two controller fixes.
"""
import sys
from pathlib import Path

Q = Path("/dev-src/qemu")


def sub(path, old, new, count=1):
    p = Q / path
    t = p.read_text()
    assert old in t, (path, old[:60])
    p.write_text(t.replace(old, new, count))


# --- spike device + build glue
(Q / "hw/ssi/spike_ssi.c").write_text(Path("/spike/spike_ssi.c").read_text())
sub("hw/ssi/meson.build", "system_ss.add(when: 'CONFIG_SSI', if_true: files('ssi.c'))",
    "system_ss.add(when: 'CONFIG_SSI', if_true: files('ssi.c', 'spike_ssi.c'))")

# --- SPI controller trace (SPI2/SPI3 only)
sub("hw/ssi/esp32_spi.c", '#include "hw/misc/esp32_flash_enc.h"\n',
    '#include "hw/misc/esp32_flash_enc.h"\n'
    'void spike_log(const char *fmt, ...) G_GNUC_PRINTF(1, 2);\n'
    'static bool spike_on(void *s)\n{\n'
    '    const char *n = object_get_canonical_path_component(OBJECT(s));\n'
    '    return n && (!strcmp(n, "spi2") || !strcmp(n, "spi3"));\n}\n'
    'static const char *spike_name(void *s)\n{\n'
    '    return object_get_canonical_path_component(OBJECT(s));\n}\n')
sub("hw/ssi/esp32_spi.c", "    }\n    return r;\n}\n",
    "    }\n"
    "    if (spike_on(s) && (addr == A_SPI_CMD || addr == A_SPI_SLAVE)) {\n"
    "        spike_log(\"%s R 0x%02x -> 0x%08\" PRIx64, spike_name(s), (unsigned)addr, r);\n"
    "    }\n"
    "    return r;\n}\n")
sub("hw/ssi/esp32_spi.c", "    Esp32SpiState *s = ESP32_SPI(opaque);\n    switch (addr) {\n    case A_SPI_W0 ... A_SPI_W0 + (ESP32_SPI_BUF_WORDS - 1) * sizeof(uint32_t):\n        s->data_reg",
    "    Esp32SpiState *s = ESP32_SPI(opaque);\n"
    "    if (spike_on(s) && addr != A_SPI_CTRL && addr != A_SPI_CTRL1 && addr != A_SPI_CTRL2) {\n"
    "        spike_log(\"%s W 0x%02x <- 0x%08\" PRIx64, spike_name(s), (unsigned)addr, value);\n"
    "    }\n"
    "    switch (addr) {\n    case A_SPI_W0 ... A_SPI_W0 + (ESP32_SPI_BUF_WORDS - 1) * sizeof(uint32_t):\n        s->data_reg")
sub("hw/ssi/esp32_spi.c", "static void esp32_spi_transaction(Esp32SpiState *s, Esp32SpiTransaction *t)\n{\n",
    "static void esp32_spi_transaction(Esp32SpiState *s, Esp32SpiTransaction *t)\n{\n"
    "    if (spike_on(s)) {\n"
    "        spike_log(\"%s xfer cmd=%d addr=%d tx=%d rx=%d pin=0x%x (CS0..2 %s)\", spike_name(s),\n"
    "                  t->cmd_bytes, t->addr_bytes, t->data_tx_bytes, t->data_rx_bytes, s->pin_reg,\n"
    "                  (s->pin_reg & 7) == 7 ? \"all disabled\" : \"some enabled\");\n"
    "    }\n")

# --- GPIO trace
sub("hw/gpio/esp32_gpio.c", '#include "hw/gpio/esp32_gpio.h"\n',
    '#include "hw/gpio/esp32_gpio.h"\nvoid spike_log(const char *fmt, ...) G_GNUC_PRINTF(1, 2);\n')
sub("hw/gpio/esp32_gpio.c", "    default:\n        break;\n    }\n    return r;",
    "    default:\n        break;\n    }\n"
    "    if (addr != A_GPIO_STRAP) {\n"
    "        spike_log(\"gpio R 0x%03x -> 0x%08\" PRIx64, (unsigned)addr, r);\n    }\n"
    "    return r;")
sub("hw/gpio/esp32_gpio.c", "                       uint64_t value, unsigned int size)\n{\n}",
    "                       uint64_t value, unsigned int size)\n{\n"
    "    spike_log(\"gpio W 0x%03x <- 0x%08\" PRIx64 \" (ignored)\", (unsigned)addr, value);\n}")

# --- Q3 hook prototype: SPI2/SPI3 on sysbus-default, unique bus names, CS wired at machine-init-done
sub("hw/ssi/esp32_spi.c", '    s->spi = ssi_create_bus(DEVICE(s), "spi");',
    '    s->spi = ssi_create_bus(DEVICE(s), NULL);   /* spike: auto name ssi.N */')
t = (Q / "hw/xtensa/esp32.c").read_text()
t = t.replace('BusState* spi_bus = qdev_get_child_bus(spi_master, "spi");',
              'BusState* spi_bus = BUS(ss->spi[1].spi);')
t = t.replace("        qdev_realize(DEVICE(&s->spi[i]), &s->periph_bus, &error_fatal);",
              "        if (i >= 2) {\n"
              "            sysbus_realize(SYS_BUS_DEVICE(&s->spi[i]), &error_fatal);\n"
              "        } else {\n"
              "            qdev_realize(DEVICE(&s->spi[i]), &s->periph_bus, &error_fatal);\n"
              "        }")
hook = '''
#include "sysemu/sysemu.h"
void spike_log(const char *fmt, ...) G_GNUC_PRINTF(1, 2);
static Notifier spike_done;
static Esp32SocState *spike_soc;
static void spike_wire_cs(Notifier *n, void *data)
{
    for (int i = 2; i < ESP32_SPI_COUNT; i++) {
        BusChild *kid;
        QTAILQ_FOREACH(kid, &BUS(spike_soc->spi[i].spi)->children, sibling) {
            SSIPeripheral *p = SSI_PERIPHERAL(kid->child);
            spike_log("machine-init-done: spi%d has %s cs=%u%s", i,
                      object_get_typename(OBJECT(p)), p->cs_index,
                      getenv("SPIKE_NO_CS_WIRE") ? " (left unwired)" : " -> wired to controller CS");
            if (getenv("SPIKE_NO_CS_WIRE") || p->cs_index >= ESP32_SPI_CS_COUNT) {
                continue;
            }
            qemu_irq cs = qdev_get_gpio_in_named(DEVICE(p), SSI_GPIO_CS, 0);
            qdev_connect_gpio_out_named(DEVICE(&spike_soc->spi[i]), SSI_GPIO_CS, p->cs_index, cs);
            qemu_set_irq(cs, 1);
        }
    }
}
'''
t = t.replace("static void esp32_machine_init(MachineState *machine)\n{", hook + "\nstatic void esp32_machine_init(MachineState *machine)\n{", 1)
t = t.replace("    esp32_machine_init_i2c(ss);\n",
              "    esp32_machine_init_i2c(ss);\n    spike_soc = ss;\n    spike_done.notify = spike_wire_cs;\n"
              "    qemu_add_machine_init_done_notifier(&spike_done);\n", 1)
(Q / "hw/xtensa/esp32.c").write_text(t)

# --- with --fixes: the two controller fixes tested in the spike ("fixed" runs)
if "--fixes" in sys.argv:
    sub("hw/ssi/esp32_spi.c", "if (byte < tx_bytes) {", "if (i < tx_bytes) {")
    sub("hw/ssi/esp32_spi.c", "if (byte < rx_bytes) {", "if (i < rx_bytes) {")
    sub("hw/ssi/esp32_spi.c",
        "if (FIELD_EX32(s->user_reg, SPI_USER, COMMAND) || FIELD_EX32(s->user2_reg, SPI_USER2, COMMAND_BITLEN)) {",
        "if (FIELD_EX32(s->user_reg, SPI_USER, COMMAND)) {")
print("spike applied")
