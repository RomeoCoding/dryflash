# Voltmeter readings are wrong

The voltmeter samples AIN0 of an ADS1115 ADC (+-4.096 V range) and prints `ain0=<volts> V`
every 250 ms. With 1.234 V applied it prints a completely different value (sometimes negative).
Make it print the applied voltage (within a few mV).
