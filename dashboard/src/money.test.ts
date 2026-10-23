import { expect, it } from "vitest";
import { formatCents, toCents } from "./money";

it("turns dollar strings into whole cents", () => {
  expect(toCents("1250.00")).toBe(125000);
  expect(toCents("1250")).toBe(125000);
  expect(toCents("1250.5")).toBe(125050);
  expect(toCents("0.00")).toBe(0);
  expect(toCents("0.07")).toBe(7);
});

it("shows whole cents as US dollars", () => {
  expect(formatCents(125000)).toBe("$1,250.00");
  expect(formatCents(42007)).toBe("$420.07");
  expect(formatCents(0)).toBe("$0.00");
  expect(formatCents(100000000)).toBe("$1,000,000.00");
});
