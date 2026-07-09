import assert from "node:assert/strict";
import test from "node:test";
import {
  defaultRouteForRole,
  navForRole,
  normalizeRole,
  ROLE_NAV,
} from "../lib/role-routes.mjs";

test("default routing sends each role to its production shell", () => {
  assert.equal(defaultRouteForRole("elder"), "/elder/companion");
  assert.equal(defaultRouteForRole("family"), "/family/overview");
  assert.equal(defaultRouteForRole("operator"), "/ops/care");
  assert.equal(defaultRouteForRole("admin"), "/ops/care");
});

test("elder and family navigation excludes operator internals", () => {
  for (const role of ["elder", "family"]) {
    const hrefs = navForRole(role).map((item) => item.href).join(" ");
    assert.equal(hrefs.includes("/ops/"), false);
    assert.equal(hrefs.includes("/traces"), false);
  }
});

test("all role navigation entries have visible labels", () => {
  for (const items of Object.values(ROLE_NAV)) {
    assert.ok(items.length > 0);
    for (const item of items) {
      assert.match(item.href, /^\//);
      assert.ok(item.label.trim().length >= 2);
      assert.ok(item.description.trim().length >= 4);
    }
  }
});

test("unknown roles degrade to elder presentation only", () => {
  assert.equal(normalizeRole(undefined), "elder");
  assert.equal(normalizeRole("guest"), "elder");
});
