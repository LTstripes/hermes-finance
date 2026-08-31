import {
  useEffect,
  useState,
  type FocusEvent,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";

import { formatMoneyInput, normalizeMoneyInput } from "../../lib/money";

type FieldProps = {
  label: string;
  htmlFor: string;
  children: ReactNode;
};

export function Field({ label, htmlFor, children }: FieldProps) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
    </div>
  );
}

type InputProps = InputHTMLAttributes<HTMLInputElement>;

export function Input({ className = "", ...rest }: InputProps) {
  return <input className={`input ${className}`.trim()} {...rest} />;
}

type MoneyInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
  onChange?: (value: string) => void;
  value?: string;
};

/** Owner-facing money input; state stays as an exact string and formats only outside editing. */
export function MoneyInput({
  className = "",
  onBlur,
  onChange,
  onFocus,
  value = "",
  ...rest
}: MoneyInputProps) {
  const [focused, setFocused] = useState(false);
  const [displayValue, setDisplayValue] = useState(() => formatMoneyInput(value));

  useEffect(() => {
    if (!focused) setDisplayValue(formatMoneyInput(value));
  }, [focused, value]);

  function handleFocus(event: FocusEvent<HTMLInputElement>) {
    setFocused(true);
    const normalized = normalizeMoneyInput(event.currentTarget.value);
    setDisplayValue(normalized ?? event.currentTarget.value.replace(/\s/g, ""));
    onFocus?.(event);
  }

  function handleBlur(event: FocusEvent<HTMLInputElement>) {
    const formatted = formatMoneyInput(event.currentTarget.value);
    setFocused(false);
    setDisplayValue(formatted);
    onChange?.(formatted);
    onBlur?.(event);
  }

  return (
    <input
      className={`input input--money ${className}`.trim()}
      onBlur={handleBlur}
      onChange={(event) => {
        setDisplayValue(event.currentTarget.value);
        onChange?.(event.currentTarget.value);
      }}
      onFocus={handleFocus}
      value={displayValue}
      {...rest}
    />
  );
}

type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

export function Select({ className = "", children, ...rest }: SelectProps) {
  return (
    <select className={`select ${className}`.trim()} {...rest}>
      {children}
    </select>
  );
}
