import type { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";

type TableProps = {
  children: ReactNode;
  className?: string;
};

export function Table({ children, className = "" }: TableProps) {
  return (
    <div className="table-wrap">
      <table className={`table ${className}`.trim()}>{children}</table>
    </div>
  );
}

type CellProps = {
  numeric?: boolean;
  children?: ReactNode;
} & TdHTMLAttributes<HTMLTableCellElement>;

export function Td({ numeric = false, className = "", children, ...rest }: CellProps) {
  return (
    <td className={`${numeric ? "num" : ""} ${className}`.trim()} {...rest}>
      {children}
    </td>
  );
}

type HeadCellProps = {
  numeric?: boolean;
  children?: ReactNode;
} & ThHTMLAttributes<HTMLTableCellElement>;

export function Th({ numeric = false, className = "", children, ...rest }: HeadCellProps) {
  return (
    <th className={`${numeric ? "num" : ""} ${className}`.trim()} {...rest}>
      {children}
    </th>
  );
}
