<template>
  <a-form :model="form" layout="vertical">
    <a-form-item name="employee_name" label="员工姓名" :rules="[{ required: true }]">
      <a-input v-model:value="form.employee_name" placeholder="如:张三" />
    </a-form-item>
    <a-form-item name="department" label="所属部门" :rules="[{ required: true }]">
      <a-select v-model:value="form.department" :options="departments" />
    </a-form-item>
    <a-form-item name="email" label="企业邮箱" :rules="[{ required: true, type: 'email' }]">
      <a-input v-model:value="form.email" />
    </a-form-item>
    <a-form-item name="start_date" label="入职日期">
      <a-date-picker v-model:value="form.start_date" />
    </a-form-item>
  </a-form>
</template>

<script setup>
const form = { employee_name: '', department: undefined, email: '', start_date: null }
const departments = []
</script>
