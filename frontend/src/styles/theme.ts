import type { GlobalThemeOverrides } from 'naive-ui'

function theme(dark: boolean): GlobalThemeOverrides {
  return { common: {
    primaryColor: dark ? '#98A8FF' : '#485FC6',
    primaryColorHover: dark ? '#B0BDFE' : '#4055B5',
    primaryColorPressed: dark ? '#8294F0' : '#35499F',
    bodyColor: dark ? '#101725' : '#F5F7FB',
    cardColor: dark ? '#1B2535' : '#FFFFFF',
    modalColor: dark ? '#1B2535' : '#FFFFFF',
    borderColor: dark ? '#35435A' : '#E3E8F1',
    textColorBase: dark ? '#EEF3FD' : '#1B2536',
    successColor: dark ? '#7ED8AF' : '#1B7D64',
    warningColor: dark ? '#F3C67C' : '#A36A17',
    errorColor: dark ? '#FF9CA7' : '#BA5057',
    borderRadius: '9px',
    fontFamily: 'Inter, "Microsoft YaHei", "PingFang SC", system-ui, sans-serif',
  } }
}

export const componentThemes = { light: theme(false), dark: theme(true) }
