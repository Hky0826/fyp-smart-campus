'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { resolveRoleId, isRolePermitted } = require('./visualisationModelService');

test('resolveRoleId maps roles accurately to MySQL IDs 1..5', () => {
    assert.equal(resolveRoleId('admin'), 1);
    assert.equal(resolveRoleId('super_admin'), 1);
    assert.equal(resolveRoleId('staff'), 2);
    assert.equal(resolveRoleId('lecturer'), 3);
    assert.equal(resolveRoleId('student'), 4);
    assert.equal(resolveRoleId('visitor'), 5);
    assert.equal(resolveRoleId('guest'), 5);
    assert.equal(resolveRoleId('unknown_role'), 5);
    assert.equal(resolveRoleId(''), 5);
    assert.equal(resolveRoleId(null), 5);
    assert.equal(resolveRoleId(3), 3);
});

test('isRolePermitted enforces role list and DENY flag', () => {
    assert.equal(isRolePermitted({ is_accessible: 'DENY', allowed_roles: '1,2,3,4,5' }, 1), false);
    assert.equal(isRolePermitted({ is_accessible: 'ALLOW', allowed_roles: '' }, 5), true);
    assert.equal(isRolePermitted({ is_accessible: 'ALLOW', allowed_roles: '1,3' }, 3), true);
    assert.equal(isRolePermitted({ is_accessible: 'ALLOW', allowed_roles: '1,3' }, 4), false);
});
