type HandoffLocationLike = {
  search?: string;
  hash?: string;
};

export function buildHandoffLocation(pathname: string, locationLike: HandoffLocationLike) {
  return {
    pathname,
    search: locationLike.search || '',
    hash: locationLike.hash || '',
  };
}
