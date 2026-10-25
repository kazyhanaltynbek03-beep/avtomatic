export const can = (auth, permission, write = false) =>
  auth?.permissions?.includes("*") ||
  auth?.permissions?.includes(permission) ||
  (!write && auth?.permissions?.includes(permission + ":read"));
