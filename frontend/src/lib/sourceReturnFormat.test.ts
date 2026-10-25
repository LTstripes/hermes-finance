import { expect, test } from "vitest";
import { formatSourceReturnRate } from "./sourceReturnFormat";

// Expected strings use Decimal(value) * 100, quantize(Decimal('.01'), ROUND_HALF_UP).
test.each([
  ["0.00124999", "0,12%"],
  ["0.00125", "0,13%"],
  ["0.001259", "0,13%"],
  ["0.00004999", "0,00%"],
  ["0.00005", "0,01%"],
  ["0.00009999", "0,01%"],
  ["0.00994999", "0,99%"],
  ["0.00995", "1,00%"],
  ["0.99995", "100,00%"],
  ["9.99995", "1000,00%"],
  ["1.25e-3", "0,13%"],
  ["1.25E+1", "1250,00%"],
  ["0E-60", "0,00%"],
  ["12345678901234567890.00005", "1234567890123456789000,01%"],
])("rounds signed Decimal fraction %s exactly, including carry", (value, expected) => {
  expect(formatSourceReturnRate(value)).toBe(expected);
  expect(formatSourceReturnRate(`-${value}`)).toBe(`−${expected}`);
});

test.each([
  ["2.674999", "2,67%"],
  ["2.675", "2,68%"],
  ["99.995", "100,00%"],
])("keeps percentage-point inputs in their own units: %s", (value, expected) => {
  expect(formatSourceReturnRate(value, false)).toBe(expected);
  expect(formatSourceReturnRate(`-${value}`, false)).toBe(`−${expected}`);
});

test.each([null, undefined, "", "NaN", "Infinity", "0x10", "1,25", "1e1000"])(
  "keeps unavailable or malformed rates unavailable: %s",
  (value) => expect(formatSourceReturnRate(value)).toBe("—"),
);
