import { useLocalSearchParams } from 'expo-router';

import { CatalogItem } from '../../../src/req/RequesterScreens';

export default function CatalogItemRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <CatalogItem id={id} />;
}
