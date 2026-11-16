import { useLocalSearchParams } from 'expo-router';

import { IncidentScreen } from '../../../src/tech/IncidentScreen';

export default function IncidentRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <IncidentScreen id={id} />;
}
