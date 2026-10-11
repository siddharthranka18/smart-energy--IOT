
#include <Arduino.h>

void setup() {
    Serial.begin(115200);
    pinMode(2, OUTPUT);

    Serial.println("Energy Management System Started");
}

void loop() {
    digitalWrite(2, HIGH);
    Serial.println("Virtual light: ON");
    delay(2000);

    digitalWrite(2, LOW);
    Serial.println("Virtual light: OFF");
    delay(2000);
}
