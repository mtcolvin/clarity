// Route -> snapshot filename, for the published static demo.
//
// THIS MUST AGREE WITH `build_static_demo.py`'s `route_key`, exactly, for every route.
// The two are separate implementations of one function, which is the classic place for a
// silent drift, so `tests/test_static_demo_key.py` executes THIS file under node against
// the Python and requires identical output. A divergence would not raise anything — it
// would just 404, i.e. a demo page that mysteriously has no data.
//
// Why a computed name rather than mirroring the URL into folders: three metrics in this
// record contain a slash ("AST/ALT Ratio"), so a mirrored path needs %2F in the request,
// and many static hosts (nginx, S3, GitHub Pages) reject or normalize an encoded slash;
// sixteen more contain spaces. Both make correctness depend on the host's URL handling.
// A name built only from [A-Za-z0-9._-] depends on nothing.
//
// The hash keeps it injective — slugging alone maps "a/b" and "a b" onto the same string.
// djb2 is not cryptographic and has no need to be: it disambiguates filenames.

function djb2(s) {
  let h = 5381
  for (let i = 0; i < s.length; i++) {
    // Math.imul keeps the multiply in int32 exactly as Python's & 0xFFFFFFFF does;
    // a plain `h * 33` would lose precision past 2^53 and diverge.
    h = (Math.imul(h, 33) ^ s.charCodeAt(i)) >>> 0
  }
  return h
}

export function routeKey(route) {
  const slug = route.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80)
  return `${slug}-${djb2(route).toString(36)}`
}
