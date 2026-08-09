import { config } from '@vue/test-utils'

config.global.stubs = {
  ElTag: { template: '<span><slot /></span>' },
  ElInput: { template: '<input />' },
  ElFormItem: { template: '<div><slot /></div>' },
  ElForm: { template: '<form><slot /></form>' },
  ElOption: { template: '<option><slot /></option>' },
  ElSelect: { template: '<select><slot /></select>' },
  ElTableColumn: { template: '<div><slot /></div>' },
  ElTable: { template: '<div><slot /></div>' },
}
