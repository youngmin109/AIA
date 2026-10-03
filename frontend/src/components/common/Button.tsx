import type { ButtonHTMLAttributes } from 'react'

const VARIANT_CLASS = {
  cta: 'cta-button',
  primary: 'primary-action',
  secondary: 'secondary-action',
  outline: 'secondary-button',
  text: 'text-action',
  icon: 'icon-button',
  iconText: 'icon-button-text',
} as const

export type ButtonVariant = keyof typeof VARIANT_CLASS

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant: ButtonVariant }

/** Console button. One place for the variant names; defaults to type="button" so it never submits by accident. */
export function Button({ variant, className, type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={className ? `${VARIANT_CLASS[variant]} ${className}` : VARIANT_CLASS[variant]} {...props} />
}
