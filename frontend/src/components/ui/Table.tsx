import type { ReactNode, TableHTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";

type TableProps = {
  children: ReactNode;
  className?: string;
} & Omit<TableHTMLAttributes<HTMLTableElement>, "className" | "children">;

export function Table({ children, className = "", ...rest }: TableProps) {
  return (
    <div className="table-wrap">
      <table className={`table ${className}`.trim()} {...rest}>
        {children}
      </table>
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
