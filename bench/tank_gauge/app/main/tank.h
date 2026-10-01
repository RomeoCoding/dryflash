#pragma once
#include <stdint.h>

/* Level transmitter: 0.5 V at the bottom of the tank, 4.5 V at 2000 mm. */
uint16_t tank_level_mm(float volts);
/* Content of the tank at a given level, from the strapping table. */
uint16_t tank_litres(uint16_t level_mm);
