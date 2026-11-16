import { useLocalSearchParams } from 'expo-router';

import { IncidentRequestDetail, ServiceRequestDetail } from '../../../../src/req/RequestDetail';

export default function RequestRoute() {
  const { kind, id } = useLocalSearchParams<{ kind: string; id: string }>();
  return kind === 'request' ? <ServiceRequestDetail id={id} /> : <IncidentRequestDetail id={id} />;
}
