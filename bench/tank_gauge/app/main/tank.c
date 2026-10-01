#include "tank.h"
#include <math.h>
#include "lut.h"

#define LEVEL_SPAN_MM 2000.0f

/* Strapping table of the site tank: horizontal cylinder, 2.0 m diameter, 6.0 m long
 * (18,850 L). Level in mm, content in litres. */
static const lut_point_t k_strapping[] = {
    {   0,     0}, { 100,   352}, { 200,   981}, { 300,  1773}, { 400,  2684},
    { 500,  3685}, { 600,  4756}, { 700,  5880}, { 800,  7041}, { 900,  8227},
    {1000,  9425}, {1100, 10623}, {1200, 11809}, {1300, 12970}, {1400, 14094},
    {1500, 15164}, {1600, 16166}, {1700, 17077}, {1800, 17869}, {1900, 18497},
    {2000, 18850},
};

uint16_t tank_level_mm(float volts)
{
    float mm = (volts - 0.5f) * (LEVEL_SPAN_MM / 4.0f);
    if (mm < 0) {
        mm = 0; /* transmitter offset near empty */
    }
    if (mm > LEVEL_SPAN_MM) {
        mm = LEVEL_SPAN_MM;
    }
    return (uint16_t)lroundf(mm);
}

uint16_t tank_litres(uint16_t level_mm)
{
    return lut_interp(k_strapping, sizeof k_strapping / sizeof k_strapping[0], level_mm);
}
