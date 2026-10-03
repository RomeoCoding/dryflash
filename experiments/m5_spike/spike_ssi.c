/*
 * THROWAWAY spike device (M5 step 0). Not part of the patch series.
 * Answers: does a transfer reach an SSI peripheral on SPI2/SPI3, and how
 * does CS move?  Returns DE AD BE EF, then 0x10 + index; logs every byte and
 * every CS edge to $SPIKE_LOG with the virtual time.
 */
#include "qemu/osdep.h"
#include "qemu/timer.h"
#include "qemu/module.h"
#include "hw/ssi/ssi.h"
#include "hw/qdev-properties.h"
#include "qom/object.h"

#define TYPE_SPIKE_SSI "spike-ssi"
OBJECT_DECLARE_SIMPLE_TYPE(SpikeSsiState, SPIKE_SSI)

struct SpikeSsiState {
    SSIPeripheral parent_obj;
    unsigned idx;
    char *tag;
};

void spike_log(const char *fmt, ...) G_GNUC_PRINTF(1, 2);
void spike_log(const char *fmt, ...)
{
    static FILE *f;
    va_list ap;

    if (!f) {
        const char *p = getenv("SPIKE_LOG");
        if (!p) {
            return;
        }
        f = fopen(p, "a");
        if (!f) {
            return;
        }
    }
    fprintf(f, "%" PRId64 " ", qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fflush(f);
}

static const uint8_t pattern[4] = { 0xde, 0xad, 0xbe, 0xef };

static uint32_t spike_transfer(SSIPeripheral *dev, uint32_t val)
{
    SpikeSsiState *s = SPIKE_SSI(dev);
    uint8_t r = s->idx < 4 ? pattern[s->idx] : 0x10 + s->idx;

    spike_log("ssi[%s] idx=%u mosi=%02x miso=%02x", s->tag, s->idx,
              val & 0xff, r);
    s->idx++;
    return r;
}

static int spike_set_cs(SSIPeripheral *dev, bool select)
{
    SpikeSsiState *s = SPIKE_SSI(dev);

    /* select is the line level; active low */
    spike_log("ssi[%s] cs=%d (%s)", s->tag, select,
              select ? "deasserted" : "ASSERTED, frame reset");
    if (!select) {
        s->idx = 0;
    }
    return 0;
}

static void spike_realize(SSIPeripheral *dev, Error **errp)
{
}

static Property spike_props[] = {
    DEFINE_PROP_STRING("tag", SpikeSsiState, tag),
    DEFINE_PROP_END_OF_LIST(),
};

static void spike_class_init(ObjectClass *klass, void *data)
{
    SSIPeripheralClass *k = SSI_PERIPHERAL_CLASS(klass);

    k->realize = spike_realize;
    k->transfer = spike_transfer;
    k->set_cs = spike_set_cs;
    k->cs_polarity = SSI_CS_LOW;
    device_class_set_props(DEVICE_CLASS(klass), spike_props);
}

static const TypeInfo spike_info = {
    .name = TYPE_SPIKE_SSI,
    .parent = TYPE_SSI_PERIPHERAL,
    .instance_size = sizeof(SpikeSsiState),
    .class_init = spike_class_init,
};

static void spike_register(void)
{
    type_register_static(&spike_info);
}
type_init(spike_register)
