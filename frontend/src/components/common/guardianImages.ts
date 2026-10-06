import guardianNormal from '../../assets/mascot/guardian-normal.png'
import guardianReview from '../../assets/mascot/guardian-review.png'
import guardianBlocked from '../../assets/mascot/guardian-blocked.png'
import guardianRecovery from '../../assets/mascot/guardian-recovery.png'
import type { GuardianState } from '../../api/guardianStatus'

export const GUARDIAN_IMAGES: Record<GuardianState, string> = {
  normal: guardianNormal,
  review: guardianReview,
  blocked: guardianBlocked,
  recovery: guardianRecovery,
}

export const GUARDIAN_ALT: Record<GuardianState, string> = {
  normal: '정상 상태의 아이아 가디언',
  review: '확인을 요청하는 아이아 가디언',
  blocked: '위험 요청을 알리는 아이아 가디언',
  recovery: '복구를 알리는 아이아 가디언',
}
