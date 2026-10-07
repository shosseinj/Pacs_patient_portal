window.config = {
  routerBasename: '/',
  showStudyList: false,
  extensions: [], modes: [],
  customizationService: { 'ohif.showPatientInfo': 'visible' },
  defaultDataSourceName: 'portal',
  dataSources: [{
    namespace: '@ohif/extension-default.dataSourcesModule.dicomweb', sourceName: 'portal',
    configuration: {
      friendlyName: 'Patient PACS', name: 'portal',
      wadoUriRoot: '/dicom-web', qidoRoot: '/dicom-web', wadoRoot: '/dicom-web',
      qidoSupportsIncludeField: true, supportsReject: false,
      imageRendering: 'wadors', thumbnailRendering: 'wadors',
      enableStudyLazyLoad: true, supportsFuzzyMatching: false, supportsWildcard: true,
      bulkDataURI: { enabled: true, relativeResolution: 'studies' },
      singlepart: 'bulkdata,video,pdf',
    },
  }],
  httpErrorHandler: function (error) {
    if (error && error.status === 401) window.top.location.assign('/portal/login');
  },
};
