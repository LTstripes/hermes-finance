import { useState, type InputHTMLAttributes } from "react";
import { Input } from "../components/ui";
import styles from "./MonthMoneyInput.module.css";

/** Display only: keep the exact owner/API string outside this component. */
export function displayMonthNumber(value: string): string {
  const match = /^([+-]?)(\d+)(?:[.,](\d*))?$/.exec(value.replace(/\s/g, ""));
  if (!match) return value;
  const fraction = match[3]?.replace(/0+$/, "");
  return `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, " ")}${fraction ? `,${fraction}` : ""}`;
}

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & {
  value: string;
  onChange: (value: string) => void;
  suffix?: string;
};

export function MonthMoneyInput({
  value,
  onChange,
  suffix = "₽",
  onFocus,
  onBlur,
  className = "",
  ...props
}: Props) {
  const [focused, setFocused] = useState(false);
  return (
    <span className={`${styles.field} ${suffix === "%" ? styles.rate : ""}`}>
      <Input
        {...props}
        className={`${styles.input} ${className}`}
        inputMode="decimal"
        type="text"
        value={focused ? value : displayMonthNumber(value)}
        onChange={(event) => onChange(event.currentTarget.value)}
        onFocus={(event) => {
          setFocused(true);
          onFocus?.(event);
        }}
        onBlur={(event) => {
          setFocused(false);
          onBlur?.(event);
        }}
      />
      <span className={styles.suffix} aria-hidden="true">
        {suffix}
      </span>
    </span>
  );
}
