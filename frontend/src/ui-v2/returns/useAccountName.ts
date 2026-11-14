import type { AccountLink } from "./model";

/** The backend resolves catalogue labels with the verified source identity. */
export function useAccountName(_links: readonly (AccountLink | null | undefined)[]) {
  return (link: AccountLink | null | undefined, fallback: string) => {
    return link?.label ?? fallback;
  };
}
